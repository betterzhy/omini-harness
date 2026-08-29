from __future__ import annotations

import json
import re
import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .anchored_fs import AnchoredPathError, AnchoredRoot
from .capability_pack_registry import (
    CapabilityVerificationSession,
    VerifiedCapabilityPack,
)
from .discussion import materialize_discussion_contract
from .generated import deterministic_json_bytes
from .hashing import canonical_json_bytes, file_sha256, sha256_bytes
from .loader import load_capabilities
from .paths import PathBoundaryError, resolve_without_symlinks, safe_relative_path
from .process_lock import ProcessLockError, exclusive_process_lock, process_lock_identity
from .project import (
    VerifiedLockContext,
    load_capability_lock,
    load_project_state,
    verify_capability_lock_context,
)
from .schema import SchemaStore

AGENT_SKILL_PROJECTION_VERSION = "agent-skill-projection/1"
CHATGPT_PROJECTION_VERSION = "chatgpt-project-pack/1"
CODEX_PROJECTION_VERSION = "codex-project-pack/1"
_VISIBILITY_RANK = {"PRIVATE": 0, "PROJECT": 1, "SHARED": 2, "PUBLIC": 3}
_PROJECTION_TRANSACTION_TOKEN = re.compile(r"^[0-9a-f]{32}$")


class ProjectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectionFreshness:
    fresh: bool
    reasons: tuple[str, ...]


def _sha256(data: bytes) -> str:
    return sha256_bytes(data)


def _projection_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _projection_data(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_projection_data(item) for item in value]
    return value


def _projection_target(root: Path, runtime: str, project_id: str, *, must_exist: bool = False) -> Path:
    return resolve_without_symlinks(
        root,
        f"generated/projections/{runtime.lower()}/{project_id}",
        must_exist=must_exist,
        label="projection pack path",
    )


def _validate_projection_swap_journal(
    target_pack: Path,
    journal: Any,
    *,
    runtime: str,
    project_id: str,
) -> dict[str, Any]:
    if not isinstance(journal, dict) or set(journal) != {
        "schemaVersion",
        "phase",
        "runtime",
        "project",
        "token",
        "hadTarget",
        "temporaryName",
        "backupName",
    }:
        raise ProjectionError("invalid projection swap recovery journal")
    token = journal.get("token")
    if (
        journal.get("schemaVersion") != "projection-swap-transaction/v1"
        or journal.get("phase") not in {"PREPARED", "COMMITTED"}
        or journal.get("runtime") != runtime
        or journal.get("project") != project_id
        or not isinstance(token, str)
        or not _PROJECTION_TRANSACTION_TOKEN.fullmatch(token)
        or not isinstance(journal.get("hadTarget"), bool)
        or journal.get("temporaryName") != f".{target_pack.name}.tmp-{token}"
        or journal.get("backupName") != f".{target_pack.name}.backup-{token}"
    ):
        raise ProjectionError("invalid projection swap recovery journal")
    return journal


def _projection_swap_journal_relative(target_relative: str) -> str:
    target = Path(target_relative)
    return (target.parent / f".{target.name}.swap-transaction.json").as_posix()


def _recover_projection_swap_anchored(
    filesystem: AnchoredRoot,
    target_relative: str,
    *,
    runtime: str,
    project_id: str,
) -> None:
    journal_relative = _projection_swap_journal_relative(target_relative)
    if not filesystem.exists(journal_relative):
        return
    try:
        journal = json.loads(filesystem.read_bytes(journal_relative))
    except (AnchoredPathError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectionError("invalid projection swap recovery journal") from exc
    target = Path(target_relative)
    journal = _validate_projection_swap_journal(
        target,
        journal,
        runtime=runtime,
        project_id=project_id,
    )
    temporary_relative = (target.parent / journal["temporaryName"]).as_posix()
    backup_relative = (target.parent / journal["backupName"]).as_posix()

    for relative, label in (
        (target_relative, "projection target"),
        (temporary_relative, "projection temporary"),
        (backup_relative, "projection backup"),
    ):
        if filesystem.exists(relative) and not filesystem.is_dir(relative):
            raise ProjectionError(f"unsafe {label} during recovery")

    if journal["phase"] == "COMMITTED":
        if not filesystem.is_dir(target_relative) or filesystem.exists(temporary_relative):
            raise ProjectionError("committed projection swap state is inconsistent")
        if filesystem.exists(backup_relative):
            filesystem.remove_tree(backup_relative)
    elif journal["hadTarget"]:
        if filesystem.exists(backup_relative):
            if filesystem.exists(target_relative):
                filesystem.remove_tree(target_relative)
            filesystem.rename(backup_relative, target_relative)
        elif not filesystem.is_dir(target_relative):
            raise ProjectionError("prepared projection swap cannot restore its original target")
        if filesystem.exists(temporary_relative):
            filesystem.remove_tree(temporary_relative)
    else:
        if filesystem.exists(backup_relative):
            raise ProjectionError("prepared projection swap has an unexpected backup")
        if filesystem.exists(target_relative):
            filesystem.remove_tree(target_relative)
        if filesystem.exists(temporary_relative):
            filesystem.remove_tree(temporary_relative)
    filesystem.unlink(journal_relative)


class ProjectionAdapter(ABC):
    runtime: str
    projection_type: str
    projection_version: str

    @abstractmethod
    def stable_guidance(self, repository_root: Path) -> str:
        raise NotImplementedError

    @abstractmethod
    def context_filename(self) -> str:
        raise NotImplementedError


class ChatGPTProjectionAdapter(ProjectionAdapter):
    runtime = "CHATGPT"
    projection_type = "CHATGPT_PROJECT_PACK"
    projection_version = CHATGPT_PROJECTION_VERSION

    def stable_guidance(self, repository_root: Path) -> str:
        return (repository_root / "runtime/templates/chatgpt-project-instructions.md").read_text(encoding="utf-8")

    def context_filename(self) -> str:
        return "resolved-context.md"


class CodexProjectionAdapter(ProjectionAdapter):
    runtime = "CODEX"
    projection_type = "CODEX_REPOSITORY_PACK"
    projection_version = CODEX_PROJECTION_VERSION

    def stable_guidance(self, repository_root: Path) -> str:
        return (repository_root / "runtime/templates/codex-repository-guidance.md").read_text(encoding="utf-8")

    def context_filename(self) -> str:
        return "resolved-task-context.md"


def _adapter(runtime: str) -> ProjectionAdapter:
    if runtime == "CHATGPT":
        return ChatGPTProjectionAdapter()
    if runtime == "CODEX":
        return CodexProjectionAdapter()
    raise ProjectionError(f"unsupported runtime projection: {runtime}")


def _authority_snapshot_from_resolved(resolved: dict[str, Any]) -> dict[str, Any] | None:
    authority_keys = {
        "authoritySnapshotFingerprint",
        "authoritySourceRevision",
        "authorityFacts",
        "authorityConflicts",
        "authorityGate",
        "authorityPaths",
    }
    present = authority_keys & set(resolved)
    if not present:
        return None
    if present != authority_keys:
        raise ProjectionError("resolved context has incomplete authority metadata")
    return {
        "snapshotFingerprint": resolved["authoritySnapshotFingerprint"],
        "sourceRevision": resolved["authoritySourceRevision"],
        "facts": resolved["authorityFacts"],
        "conflicts": resolved["authorityConflicts"],
        "gate": resolved["authorityGate"],
        "authorities": resolved["authorityPaths"],
    }


def _verify_resolved_context(
    repository_root: Path,
    project_root: Path,
    resolved: dict[str, Any],
    *,
    runtime: str,
    authority_snapshot: dict[str, Any] | None = None,
    verification_session: CapabilityVerificationSession | None = None,
) -> None:
    from .resolver import resolve_design_context

    embedded_snapshot = _authority_snapshot_from_resolved(resolved)
    if embedded_snapshot is not None:
        if authority_snapshot is None:
            raise ProjectionError("live authority snapshot is required for this resolved context")
        live_snapshot = {
            "snapshotFingerprint": authority_snapshot.get("snapshotFingerprint"),
            "sourceRevision": authority_snapshot.get("sourceRevision"),
            "facts": authority_snapshot.get("facts"),
            "conflicts": authority_snapshot.get("conflicts"),
            "gate": authority_snapshot.get("gate"),
            "authorities": authority_snapshot.get("authorities"),
        }
        if embedded_snapshot != live_snapshot:
            raise ProjectionError("resolved context authority metadata does not match the live snapshot")
    elif authority_snapshot is not None:
        raise ProjectionError("resolved context is missing the supplied live authority snapshot")
    try:
        expected = resolve_design_context(
            repository_root,
            project_root,
            intent=resolved["intent"],
            topic=resolved["topic"],
            requested_output=resolved["requestedOutput"],
            runtime=runtime,
            explicit_stage=resolved["stage"],
            reopen_signal=resolved.get("reopenSignal"),
            authority_snapshot=authority_snapshot,
            verification_session=verification_session,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectionError("resolved context is invalid for the current resolver") from exc
    if resolved != expected:
        raise ProjectionError("resolved context was not produced by the current resolver")


def _can_materialize(visibility: str, target_visibility: str = "PROJECT") -> bool:
    return _VISIBILITY_RANK.get(visibility, -1) >= _VISIBILITY_RANK[target_visibility]


def _capability_maps(root: Path) -> dict[tuple[str, str], Any]:
    by_version = {(cap.id, cap.version): cap for cap in load_capabilities(root)}
    return by_version


def _resolved_context_markdown(resolved: dict[str, Any]) -> str:
    lines = [
        "# Resolved Design Context",
        "",
        f"- Resolution: `{resolved['resolutionId']}`",
        f"- Project: `{resolved['project']}`",
        f"- Topic: `{resolved['topic']}`",
        f"- Stage: `{resolved['stage']}`",
        f"- Intent: `{resolved['intent']}`",
        f"- Topic Guard: `{resolved['topicGuard']}`",
        "",
        "## Selected Capabilities",
    ]
    for item in resolved.get("selectedCapabilities", []):
        lines.append(f"- `{item['id']}@{item['version']}` hash `{item['contentHash']}`")
    lines += ["", "## Project Authority References"]
    lines += [f"- `{ref}`" for ref in resolved.get("projectAuthorityReferences", [])] or ["- None"]
    lines += ["", "## Human Gates"]
    lines += [f"- {gate}" for gate in resolved.get("humanGates", [])] or ["- None"]
    lines += ["", "## Conflict Signals"]
    if resolved.get("conflictSignals"):
        for signal in resolved["conflictSignals"]:
            lines.append(
                f"- `{signal['sharedCapability']}` vs `{signal['projectReference']}` → `{signal['resolutionRule']}`"
            )
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def _render_skill(
    skill_capability: Any,
    selected_index: dict[str, dict[str, Any]],
    by_version: dict[tuple[str, str], Any],
    omitted: list[dict[str, str]],
) -> str:
    asset = skill_capability.asset
    refs: list[str] = []
    for value in [
        *asset.get("skill", {}).get("referencedCapabilities", []),
        *asset.get("relationships", {}).get("dependsOn", []),
    ]:
        if value not in refs:
            refs.append(value)
    referenced_sections: list[str] = []
    for ref in refs:
        selected = selected_index.get(ref)
        if selected is None or selected.get("kind") not in {"PRINCIPLE", "FRAMEWORK"}:
            continue
        cap = by_version.get((ref, selected["version"]))
        if cap is None:
            continue
        if not _can_materialize(cap.asset.get("visibility", "PRIVATE")):
            marker = {"id": ref, "reason": "visibility-gate"}
            if marker not in omitted:
                omitted.append(marker)
            continue
        referenced_sections.extend(
            [
                f"### {ref}@{cap.version}",
                "",
                cap.content.strip(),
                "",
            ]
        )
    identity = skill_capability.id
    name = identity.rsplit(":", 1)[-1]
    return "\n".join(
        [
            "---",
            f"name: {name}",
            f"description: {asset['summary']}",
            "---",
            "",
            "<!-- agent-evolution-source",
            f"sourceCapabilityId: {identity}",
            f"sourceCapabilityVersion: {skill_capability.version}",
            f"sourceContentHash: {skill_capability.content_hash}",
            f"projectionVersion: {AGENT_SKILL_PROJECTION_VERSION}",
            "-->",
            "",
            skill_capability.content.strip(),
            "",
            "## Referenced Canonical Guidance",
            "",
            *(referenced_sections or ["No referenced Principle/Framework content was materialized for this projection.", ""]),
        ]
    )


def _external_source_capability(
    selected: dict[str, Any],
    locked: Mapping[str, Any],
    verified_pack: VerifiedCapabilityPack,
) -> dict[str, Any]:
    registration = verified_pack.registration
    if (
        selected.get("sourceKind") != "EXTERNAL_CAPABILITY_PACK"
        or selected.get("sourceRegistrationId") != locked["sourceRegistrationId"]
        or registration.get("registrationId") != locked["sourceRegistrationId"]
        or selected.get("version") != locked["resolvedVersion"]
        or selected.get("contentHash") != locked["contentHash"]
    ):
        raise ProjectionError(f"resolved external capability provenance drift: {selected.get('id')}")
    return {
        "id": selected["id"],
        "kind": selected["kind"],
        "version": selected["version"],
        "contentHash": selected["contentHash"],
        "sourceKind": "EXTERNAL_CAPABILITY_PACK",
        "sourceRegistrationId": locked["sourceRegistrationId"],
        "sourceCommit": locked["sourceCommit"],
        "sourceTree": locked["sourceTree"],
        "resolvedContentDigest": locked["resolvedContentDigest"],
        "validatorIdentity": _projection_data(locked["validatorIdentity"]),
        "registrationFingerprint": locked["registrationFingerprint"],
    }


def _external_skill_payload(
    source: dict[str, Any], verified_pack: VerifiedCapabilityPack
) -> tuple[dict[str, bytes], dict[str, Any]]:
    registration = verified_pack.registration
    manifest = verified_pack.manifest
    if not isinstance(manifest, Mapping):
        raise ProjectionError("external capability pack manifest is unavailable")
    skill_name = manifest.get("skillName")
    skill_path = manifest.get("skillPath")
    if not isinstance(skill_name, str) or not isinstance(skill_path, str):
        raise ProjectionError("external capability pack Skill declaration is invalid")
    if skill_path != f"skills/{skill_name}/SKILL.md":
        raise ProjectionError("external capability pack Skill declaration path drift")
    relative = f"skills/{skill_name}/SKILL.md"
    declaration = registration.get("contentDeclaration", {})
    projection_contract = declaration.get("projectionContract")
    try:
        if projection_contract == "SELF_CONTAINED_SKILL_BUNDLE":
            source_blobs = verified_pack.read_blobs()
            skill_bytes = source_blobs[skill_path]
            payloads: dict[str, bytes] = {}
            resource_files: list[dict[str, str]] = []
            for source_path, data in sorted(source_blobs.items()):
                target_path = (
                    relative
                    if source_path == skill_path
                    else f"skills/{skill_name}/{source_path}"
                )
                if target_path in payloads:
                    raise ValueError("self-contained Skill resource path collision")
                payloads[target_path] = data
                resource_files.append(
                    {
                        "sourcePath": source_path,
                        "path": target_path,
                        "sha256": _sha256(data),
                    }
                )
        else:
            skill_bytes = verified_pack.read_blob(skill_path)
            payloads = {relative: skill_bytes}
            resource_files = []
        skill_text = skill_bytes.decode("utf-8", "strict")
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise ProjectionError("external capability pack Skill blob is invalid") from exc
    if not skill_text.startswith("---\n"):
        raise ProjectionError("external capability pack Skill front matter is missing")
    end = skill_text.find("\n---\n", 4)
    if end < 0:
        raise ProjectionError("external capability pack Skill front matter is invalid")
    try:
        front_matter = yaml.safe_load(skill_text[4:end])
    except yaml.YAMLError as exc:
        raise ProjectionError("external capability pack Skill front matter is invalid") from exc
    if not isinstance(front_matter, dict) or front_matter.get("name") != skill_name:
        raise ProjectionError("external capability pack Skill front matter name drift")
    generated = {
        "id": source["id"],
        "version": source["version"],
        "contentHash": source["contentHash"],
        "skillProjectionVersion": AGENT_SKILL_PROJECTION_VERSION,
        "path": relative,
        "sourceKind": "EXTERNAL_CAPABILITY_PACK",
        "sourceRegistrationId": source["sourceRegistrationId"],
        "sourceCommit": source["sourceCommit"],
        "sourceTree": source["sourceTree"],
        "resolvedContentDigest": source["resolvedContentDigest"],
        "validatorIdentity": source["validatorIdentity"],
        "registrationFingerprint": source["registrationFingerprint"],
        "sourceSkillPath": skill_path,
        "skillBlobSha256": "sha256:" + _sha256(skill_bytes),
    }
    if projection_contract == "SELF_CONTAINED_SKILL_BUNDLE":
        generated.update(
            {
                "projectionContract": projection_contract,
                "resourceSetDigest": "sha256:"
                + sha256_bytes(canonical_json_bytes(resource_files)),
                "resourceFiles": resource_files,
            }
        )
    return payloads, generated


def _verify_external_source_snapshot(
    repository_root: Path,
    project_root: Path,
    expected_context: VerifiedLockContext,
    *,
    verification_session: CapabilityVerificationSession | None = None,
) -> None:
    external_ids = {
        item["capabilityId"]
        for item in expected_context.lock["capabilities"]
        if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK"
    }
    if not external_ids:
        return
    if verification_session is None:
        raise ProjectionError("external source verification session is unavailable")
    try:
        live_context = verify_capability_lock_context(
            repository_root,
            project_root,
            verification_session=verification_session,
        )
    except Exception as exc:
        raise ProjectionError("external source identity drift during projection") from exc
    if live_context is not expected_context:
        raise ProjectionError("external source identity drift during projection")
    for capability_id in sorted(external_ids):
        if (
            live_context.verified_packs.get(capability_id)
            is not expected_context.verified_packs.get(capability_id)
        ):
            raise ProjectionError("external source identity drift during projection")


def _build_projection_pack_unlocked(
    repository_root: Path,
    project_root: Path,
    resolved_context: dict[str, Any],
    *,
    runtime: str,
    authority_snapshot: dict[str, Any] | None = None,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:
    root = Path(repository_root)
    project = Path(project_root)
    adapter = _adapter(runtime)
    if resolved_context.get("runtime") != runtime:
        raise ProjectionError("resolved context runtime does not match projection runtime")
    if verification_session is None:
        declared_lock = load_capability_lock(root, project)
        external_ids = {
            item["capabilityId"]
            for item in declared_lock["capabilities"]
            if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK"
        }
        with CapabilityVerificationSession(
            root,
            allowed_capability_ids=external_ids,
        ) as private_session:
            return _build_projection_pack_unlocked(
                root,
                project,
                resolved_context,
                runtime=runtime,
                authority_snapshot=authority_snapshot,
                verification_session=private_session,
            )
    lock_context = verify_capability_lock_context(
        root,
        project,
        verification_session=verification_session,
    )
    lock = lock_context.lock
    if resolved_context.get("capabilityLockFingerprint") != lock["lockFingerprint"]:
        raise ProjectionError("resolved context capability lock is stale")
    if resolved_context.get("project") != lock["project"]:
        raise ProjectionError("resolved context project does not match capability lock")
    _verify_resolved_context(
        root,
        project,
        resolved_context,
        runtime=runtime,
        authority_snapshot=authority_snapshot,
        verification_session=verification_session,
    )
    try:
        project_identity = safe_relative_path(resolved_context["project"], label="projection project")
    except (KeyError, PathBoundaryError) as exc:
        raise ProjectionError("resolved context project is not a safe identity") from exc
    if len(project_identity.parts) != 1:
        raise ProjectionError("resolved context project is not a safe identity")
    by_version = _capability_maps(root)
    locked_index = {item["capabilityId"]: item for item in lock["capabilities"]}
    source_capabilities: list[dict[str, Any]] = []
    selected_index: dict[str, dict[str, Any]] = {}
    for item in sorted(resolved_context.get("selectedCapabilities", []), key=lambda value: value["id"]):
        if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK":
            verified_pack = lock_context.verified_packs.get(item["id"])
            locked = locked_index.get(item["id"])
            if verified_pack is None or locked is None:
                raise ProjectionError(f"resolved external capability is not locked: {item['id']}")
            source = _external_source_capability(item, locked, verified_pack)
            source_capabilities.append(source)
            selected_index[item["id"]] = source
            continue
        current = by_version.get((item["id"], item["version"]))
        if current is None or current.content_hash != item["contentHash"]:
            raise ProjectionError(f"resolved context is stale for {item['id']}")
        source = {
            "id": item["id"],
            "kind": item["kind"],
            "version": item["version"],
            "contentHash": item["contentHash"],
        }
        source_capabilities.append(source)
        selected_index[item["id"]] = source

    try:
        target_pack = _projection_target(root.resolve(), runtime, project_identity.as_posix())
    except PathBoundaryError as exc:
        raise ProjectionError("projection output path contains a symlink") from exc
    try:
        target_relative = target_pack.relative_to(root.resolve()).as_posix()
        target_relative_path = Path(target_relative)
        parent_relative = target_relative_path.parent.as_posix()
        token = uuid.uuid4().hex
        pack_relative = (target_relative_path.parent / f".{target_pack.name}.tmp-{token}").as_posix()
        backup_relative = (target_relative_path.parent / f".{target_pack.name}.backup-{token}").as_posix()
        journal_relative = _projection_swap_journal_relative(target_relative)
        with AnchoredRoot(root.resolve()) as filesystem:
            filesystem.mkdirs(parent_relative)
            _recover_projection_swap_anchored(
                filesystem,
                target_relative,
                runtime=runtime,
                project_id=project_identity.as_posix(),
            )
            filesystem.mkdir_new(pack_relative)
            try:
                stable_name = "project-instructions.md" if runtime == "CHATGPT" else "repository-guidance.md"
                generated_payloads: dict[str, bytes] = {
                    stable_name: adapter.stable_guidance(root).encode("utf-8"),
                    adapter.context_filename(): _resolved_context_markdown(resolved_context).encode("utf-8"),
                    "resolved-context.json": deterministic_json_bytes(resolved_context),
                    "discussion-contract.md": materialize_discussion_contract(
                        root, project, resolved_context
                    ).encode("utf-8"),
                }

                omitted_references: list[dict[str, str]] = []
                generated_skills: list[dict[str, Any]] = []
                for source in source_capabilities:
                    if source.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK":
                        verified_pack = lock_context.verified_packs[source["id"]]
                        skill_payloads, generated = _external_skill_payload(
                            source, verified_pack
                        )
                        for relative, data in skill_payloads.items():
                            if relative in generated_payloads:
                                raise ProjectionError(
                                    f"projection generated file collision: {relative}"
                                )
                            generated_payloads[relative] = data
                        generated_skills.append(generated)
                        continue
                    if source["kind"] != "SKILL":
                        continue
                    capability = by_version[(source["id"], source["version"])]
                    if not _can_materialize(capability.asset.get("visibility", "PRIVATE")):
                        marker = {"id": source["id"], "reason": "visibility-gate"}
                        if marker not in omitted_references:
                            omitted_references.append(marker)
                        continue
                    name = source["id"].rsplit(":", 1)[-1]
                    relative = f"skills/{name}/SKILL.md"
                    generated_payloads[relative] = _render_skill(
                        capability, selected_index, by_version, omitted_references
                    ).encode("utf-8")
                    generated_skills.append(
                        {
                            "id": source["id"],
                            "version": source["version"],
                            "contentHash": source["contentHash"],
                            "skillProjectionVersion": AGENT_SKILL_PROJECTION_VERSION,
                            "path": relative,
                        }
                    )

                _verify_external_source_snapshot(
                    root,
                    project,
                    lock_context,
                    verification_session=verification_session,
                )

                generated_files = [
                    {"path": relative, "sha256": _sha256(data)}
                    for relative, data in sorted(generated_payloads.items())
                ]
                manifest = {
                    "schemaVersion": "runtime-projection-manifest/v1",
                    "projectionType": adapter.projection_type,
                    "projectionVersion": adapter.projection_version,
                    "runtime": runtime,
                    "project": resolved_context["project"],
                    "sourceResolutionId": resolved_context["resolutionId"],
                    "capabilityLockFingerprint": resolved_context["capabilityLockFingerprint"],
                    "projectStateHash": resolved_context["projectStateHash"],
                    "projectBindingHash": resolved_context["projectBindingHash"],
                    "sourceCapabilities": source_capabilities,
                    "generatedSkills": generated_skills,
                    "omittedReferences": sorted(omitted_references, key=lambda item: (item["id"], item["reason"])),
                    "generatedFiles": generated_files,
                }
                if "authoritySnapshotFingerprint" in resolved_context:
                    manifest.update(
                        {
                            "authoritySnapshotFingerprint": resolved_context["authoritySnapshotFingerprint"],
                            "authoritySourceRevision": resolved_context["authoritySourceRevision"],
                            "authorityGate": resolved_context["authorityGate"],
                        }
                    )
                generated_payloads["projection-manifest.json"] = deterministic_json_bytes(manifest)
                for relative, data in sorted(generated_payloads.items()):
                    filesystem.write_bytes(f"{pack_relative}/{relative}", data)

                _verify_external_source_snapshot(
                    root,
                    project,
                    lock_context,
                    verification_session=verification_session,
                )

                journal = {
                    "schemaVersion": "projection-swap-transaction/v1",
                    "phase": "PREPARED",
                    "runtime": runtime,
                    "project": project_identity.as_posix(),
                    "token": token,
                    "hadTarget": filesystem.exists(target_relative),
                    "temporaryName": Path(pack_relative).name,
                    "backupName": Path(backup_relative).name,
                }
                filesystem.write_bytes(journal_relative, deterministic_json_bytes(journal))
                if journal["hadTarget"]:
                    if not filesystem.is_dir(target_relative):
                        raise ProjectionError("unsafe projection target before swap")
                    filesystem.rename(target_relative, backup_relative)
                filesystem.rename(pack_relative, target_relative)
                _verify_external_source_snapshot(
                    root,
                    project,
                    lock_context,
                    verification_session=verification_session,
                )
                journal["phase"] = "COMMITTED"
                filesystem.write_bytes(journal_relative, deterministic_json_bytes(journal))
                if filesystem.exists(backup_relative):
                    filesystem.remove_tree(backup_relative)
                filesystem.unlink(journal_relative)
                return manifest
            except BaseException:
                if filesystem.exists(journal_relative):
                    _recover_projection_swap_anchored(
                        filesystem,
                        target_relative,
                        runtime=runtime,
                        project_id=project_identity.as_posix(),
                    )
                elif filesystem.exists(pack_relative):
                    filesystem.remove_tree(pack_relative)
                raise
    except (ValueError, AnchoredPathError) as exc:
        raise ProjectionError("projection output path contains a symlink or escaped its anchored root") from exc


def build_projection_pack(
    repository_root: Path,
    project_root: Path,
    resolved_context: dict[str, Any],
    *,
    runtime: str,
    authority_snapshot: dict[str, Any] | None = None,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:
    project_id = resolved_context.get("project", "invalid-project")
    target = Path(repository_root).resolve() / "generated" / "projections" / runtime.lower() / str(project_id)
    identity = process_lock_identity("projection-pack", target)
    try:
        with exclusive_process_lock(identity):
            return _build_projection_pack_unlocked(
                repository_root,
                project_root,
                resolved_context,
                runtime=runtime,
                authority_snapshot=authority_snapshot,
                verification_session=verification_session,
            )
    except ProcessLockError as exc:
        raise ProjectionError(f"concurrent projection build rejected: {exc}") from exc


def validate_projection_pack(
    repository_root: Path,
    project_root: Path,
    pack_root: Path,
    *,
    runtime: str,
    authority_snapshot: dict[str, Any] | None = None,
    verification_session: CapabilityVerificationSession | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(repository_root).resolve()
    project = Path(project_root)
    adapter = _adapter(runtime)
    state = load_project_state(root, project)
    try:
        expected_pack = _projection_target(root, runtime, state["project"], must_exist=True)
    except (PathBoundaryError, FileNotFoundError) as exc:
        raise ProjectionError("canonical projection output path is unsafe or missing") from exc
    pack = Path(pack_root).resolve(strict=True)
    if pack != expected_pack:
        raise ProjectionError("projection pack is outside the canonical generated projections root")
    if any(path.is_symlink() for path in pack.rglob("*")):
        raise ProjectionError("canonical projection contains a symlink")
    manifest_path = pack / "projection-manifest.json"
    context_path = pack / "resolved-context.json"
    if not manifest_path.is_file() or not context_path.is_file():
        raise ProjectionError("canonical projection manifest or resolved context is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    resolved = json.loads(context_path.read_text(encoding="utf-8"))
    SchemaStore(root).validate("core/schemas/runtime-projection-manifest.schema.json", manifest)
    if verification_session is None:
        declared_lock = load_capability_lock(root, project)
        external_ids = {
            item["capabilityId"]
            for item in declared_lock["capabilities"]
            if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK"
        }
        with CapabilityVerificationSession(
            root,
            allowed_capability_ids=external_ids,
        ) as private_session:
            return validate_projection_pack(
                root,
                project,
                pack,
                runtime=runtime,
                authority_snapshot=authority_snapshot,
                verification_session=private_session,
            )
    lock_context = verify_capability_lock_context(
        root,
        project,
        verification_session=verification_session,
    )
    lock = lock_context.lock
    if resolved.get("project") != state["project"] or resolved.get("runtime") != runtime:
        raise ProjectionError("canonical projection resolved context identity mismatch")
    if resolved.get("capabilityLockFingerprint") != lock["lockFingerprint"]:
        raise ProjectionError("canonical projection lock mismatch")
    if manifest.get("sourceResolutionId") != resolved.get("resolutionId"):
        raise ProjectionError("canonical projection resolution mismatch")
    if manifest.get("project") != state["project"] or manifest.get("runtime") != runtime:
        raise ProjectionError("canonical projection manifest identity mismatch")
    if manifest.get("capabilityLockFingerprint") != lock["lockFingerprint"]:
        raise ProjectionError("canonical projection manifest lock mismatch")
    _verify_resolved_context(
        root,
        project,
        resolved,
        runtime=runtime,
        authority_snapshot=authority_snapshot,
        verification_session=verification_session,
    )
    state_path = project / ".agent-evolution/design-state.yaml"
    binding_path = project / ".agent-evolution/capabilities.yaml"
    if resolved.get("projectStateHash") != file_sha256(state_path) or resolved.get("projectBindingHash") != file_sha256(binding_path):
        raise ProjectionError("canonical projection control-plane drift")

    by_version = _capability_maps(root)
    locked_index = {item["capabilityId"]: item for item in lock["capabilities"]}
    selected_index: dict[str, dict[str, Any]] = {}
    source_capabilities: list[dict[str, Any]] = []
    for item in sorted(resolved.get("selectedCapabilities", []), key=lambda value: value["id"]):
        if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK":
            verified_pack = lock_context.verified_packs.get(item["id"])
            locked = locked_index.get(item["id"])
            if verified_pack is None or locked is None:
                raise ProjectionError(f"canonical projection external lock drift: {item['id']}")
            source = _external_source_capability(item, locked, verified_pack)
            source_capabilities.append(source)
            selected_index[item["id"]] = source
            continue
        capability = by_version.get((item["id"], item["version"]))
        if capability is None or capability.content_hash != item["contentHash"]:
            raise ProjectionError(f"canonical projection capability drift: {item['id']}")
        source = {
            "id": item["id"],
            "kind": item["kind"],
            "version": item["version"],
            "contentHash": item["contentHash"],
        }
        source_capabilities.append(source)
        selected_index[item["id"]] = source
    if manifest.get("sourceCapabilities") != source_capabilities:
        raise ProjectionError("canonical projection source capability mismatch")

    stable_name = "project-instructions.md" if runtime == "CHATGPT" else "repository-guidance.md"
    expected_bytes: dict[str, bytes] = {
        stable_name: adapter.stable_guidance(root).encode("utf-8"),
        adapter.context_filename(): _resolved_context_markdown(resolved).encode("utf-8"),
        "resolved-context.json": deterministic_json_bytes(resolved),
        "discussion-contract.md": materialize_discussion_contract(root, project, resolved).encode("utf-8"),
    }
    omitted: list[dict[str, str]] = []
    generated_skills: list[dict[str, Any]] = []
    for source in source_capabilities:
        if source.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK":
            skill_payloads, generated = _external_skill_payload(
                source, lock_context.verified_packs[source["id"]]
            )
            for relative, data in skill_payloads.items():
                if relative in expected_bytes:
                    raise ProjectionError(
                        f"canonical projection file collision: {relative}"
                    )
                expected_bytes[relative] = data
            generated_skills.append(generated)
            continue
        if source["kind"] != "SKILL":
            continue
        capability = by_version[(source["id"], source["version"])]
        if not _can_materialize(capability.asset.get("visibility", "PRIVATE")):
            marker = {"id": source["id"], "reason": "visibility-gate"}
            if marker not in omitted:
                omitted.append(marker)
            continue
        name = source["id"].rsplit(":", 1)[-1]
        relative = f"skills/{name}/SKILL.md"
        expected_bytes[relative] = _render_skill(capability, selected_index, by_version, omitted).encode("utf-8")
        generated_skills.append(
            {
                "id": source["id"],
                "version": source["version"],
                "contentHash": source["contentHash"],
                "skillProjectionVersion": AGENT_SKILL_PROJECTION_VERSION,
                "path": relative,
            }
        )
    if manifest.get("generatedSkills") != generated_skills:
        raise ProjectionError("canonical projection generated skill mismatch")
    if manifest.get("omittedReferences") != sorted(omitted, key=lambda item: (item["id"], item["reason"])):
        raise ProjectionError("canonical projection omitted reference mismatch")
    expected_files = [
        {"path": relative, "sha256": _sha256(data)}
        for relative, data in sorted(expected_bytes.items())
    ]
    if manifest.get("generatedFiles") != expected_files:
        raise ProjectionError("canonical projection generated file manifest mismatch")
    if "authoritySnapshotFingerprint" in resolved:
        for key in ("authoritySnapshotFingerprint", "authoritySourceRevision", "authorityGate"):
            if manifest.get(key) != resolved.get(key):
                raise ProjectionError(f"canonical projection authority metadata mismatch: {key}")
    actual_files = {path.relative_to(pack).as_posix() for path in pack.rglob("*") if path.is_file()}
    if actual_files != set(expected_bytes) | {"projection-manifest.json"}:
        raise ProjectionError("canonical projection file set mismatch")
    for relative, data in expected_bytes.items():
        path = pack / relative
        if path.read_bytes() != data:
            raise ProjectionError(f"canonical projection file bytes mismatch: {relative}")
    _verify_external_source_snapshot(
        root,
        project,
        lock_context,
        verification_session=verification_session,
    )
    return manifest, resolved


def check_projection_freshness(
    repository_root: Path,
    project_root: Path,
    *,
    runtime: str,
    authority_snapshot: dict[str, Any] | None = None,
    expected_resolution_id: str | None = None,
    verification_session: CapabilityVerificationSession | None = None,
) -> ProjectionFreshness:
    root = Path(repository_root)
    project = Path(project_root)
    try:
        adapter = _adapter(runtime)
    except ProjectionError as exc:
        return ProjectionFreshness(False, (str(exc),))
    try:
        state = load_project_state(root, project)
        project_identity = safe_relative_path(state["project"], label="projection project")
        if len(project_identity.parts) != 1:
            raise PathBoundaryError("projection project must be one path segment")
        pack = _projection_target(root.resolve(), runtime, project_identity.as_posix())
    except Exception:
        return ProjectionFreshness(False, ("project-state-invalid",))
    manifest_path = pack / "projection-manifest.json"
    if not manifest_path.exists():
        return ProjectionFreshness(False, ("projection-missing",))
    if verification_session is None:
        try:
            declared_lock = load_capability_lock(root, project)
            external_ids = {
                item["capabilityId"]
                for item in declared_lock["capabilities"]
                if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK"
            }
        except Exception:
            return ProjectionFreshness(False, ("projection-integrity-drift",))
        with CapabilityVerificationSession(
            root,
            allowed_capability_ids=external_ids,
        ) as private_session:
            return check_projection_freshness(
                root,
                project,
                runtime=runtime,
                authority_snapshot=authority_snapshot,
                expected_resolution_id=expected_resolution_id,
                verification_session=private_session,
            )
    try:
        manifest, _ = validate_projection_pack(
            root,
            project,
            pack,
            runtime=runtime,
            authority_snapshot=authority_snapshot,
            verification_session=verification_session,
        )
    except Exception:
        return ProjectionFreshness(False, ("projection-integrity-drift",))
    reasons: set[str] = set()
    if manifest.get("projectionVersion") != adapter.projection_version:
        reasons.add("projection-version-changed")
    if expected_resolution_id is not None and manifest.get("sourceResolutionId") != expected_resolution_id:
        reasons.add("resolution-context-drift")
    try:
        lock_context = verify_capability_lock_context(
            root,
            project,
            verification_session=verification_session,
        )
        lock = lock_context.lock
    except Exception:
        lock = None
        reasons.add("capability-lock-drift")
    if lock is not None and manifest.get("capabilityLockFingerprint") != lock["lockFingerprint"]:
        reasons.add("capability-lock-drift")
    state_path = project / ".agent-evolution/design-state.yaml"
    binding_path = project / ".agent-evolution/capabilities.yaml"
    if not state_path.exists() or manifest.get("projectStateHash") != file_sha256(state_path):
        reasons.add("project-state-drift")
    if not binding_path.exists() or manifest.get("projectBindingHash") != file_sha256(binding_path):
        reasons.add("project-binding-drift")
    if "authoritySnapshotFingerprint" in manifest:
        if authority_snapshot is None:
            reasons.add("authority-snapshot-required")
        elif (
            manifest.get("authoritySnapshotFingerprint") != authority_snapshot.get("snapshotFingerprint")
            or manifest.get("authoritySourceRevision") != authority_snapshot.get("sourceRevision")
        ):
            reasons.add("authority-snapshot-drift")
    by_version = _capability_maps(root)
    for source in manifest.get("sourceCapabilities", []):
        if source.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK":
            continue
        current = by_version.get((source["id"], source["version"]))
        if current is None or current.content_hash != source["contentHash"]:
            reasons.add("source-capability-hash-changed")
    for item in manifest.get("generatedFiles", []):
        path = pack / item["path"]
        if not path.exists() or file_sha256(path) != item["sha256"]:
            reasons.add("generated-file-drift")
    return ProjectionFreshness(not reasons, tuple(sorted(reasons)))
