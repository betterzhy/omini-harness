from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .discussion import materialize_discussion_contract
from .generated import deterministic_json_bytes, write_generated_json
from .hashing import file_sha256, sha256_bytes
from .loader import load_capabilities
from .paths import PathBoundaryError, resolve_without_symlinks, safe_relative_path
from .project import load_project_state, verify_capability_lock
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


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass


def _write_atomic(path: Path, data: bytes) -> None:
    temporary = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _projection_target(root: Path, runtime: str, project_id: str, *, must_exist: bool = False) -> Path:
    return resolve_without_symlinks(
        root,
        f"generated/projections/{runtime.lower()}/{project_id}",
        must_exist=must_exist,
        label="projection pack path",
    )


def _projection_swap_journal_path(target_pack: Path) -> Path:
    path = target_pack.parent / f".{target_pack.name}.swap-transaction.json"
    if path.is_symlink():
        raise ProjectionError("projection swap journal must not be a symlink")
    return path


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


def _remove_projection_directory(path: Path, *, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ProjectionError(f"unsafe {label}")
    shutil.rmtree(path)
    _fsync_directory(path.parent)


def _recover_projection_swap(target_pack: Path, *, runtime: str, project_id: str) -> None:
    journal_path = _projection_swap_journal_path(target_pack)
    if not journal_path.exists():
        return
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectionError("invalid projection swap recovery journal") from exc
    journal = _validate_projection_swap_journal(
        target_pack,
        journal,
        runtime=runtime,
        project_id=project_id,
    )
    temporary = target_pack.parent / journal["temporaryName"]
    backup = target_pack.parent / journal["backupName"]
    for path, label in ((target_pack, "projection target"), (temporary, "projection temporary"), (backup, "projection backup")):
        if path.is_symlink():
            raise ProjectionError(f"unsafe {label} during recovery")

    if journal["phase"] == "COMMITTED":
        if not target_pack.is_dir() or temporary.exists():
            raise ProjectionError("committed projection swap state is inconsistent")
        if backup.exists():
            _remove_projection_directory(backup, label="projection backup")
    elif journal["hadTarget"]:
        if backup.exists():
            if target_pack.exists():
                _remove_projection_directory(target_pack, label="projection target")
            backup.replace(target_pack)
            _fsync_directory(target_pack.parent)
        elif not target_pack.is_dir():
            raise ProjectionError("prepared projection swap cannot restore its original target")
        if temporary.exists():
            _remove_projection_directory(temporary, label="projection temporary")
    else:
        if backup.exists():
            raise ProjectionError("prepared projection swap has an unexpected backup")
        if target_pack.exists():
            _remove_projection_directory(target_pack, label="projection target")
        if temporary.exists():
            _remove_projection_directory(temporary, label="projection temporary")
    journal_path.unlink()
    _fsync_directory(journal_path.parent)


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
) -> None:
    from .resolver import resolve_design_context

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
            authority_snapshot=_authority_snapshot_from_resolved(resolved),
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


def build_projection_pack(
    repository_root: Path,
    project_root: Path,
    resolved_context: dict[str, Any],
    *,
    runtime: str,
) -> dict[str, Any]:
    root = Path(repository_root)
    project = Path(project_root)
    adapter = _adapter(runtime)
    if resolved_context.get("runtime") != runtime:
        raise ProjectionError("resolved context runtime does not match projection runtime")
    lock, _ = verify_capability_lock(root, project)
    if resolved_context.get("capabilityLockFingerprint") != lock["lockFingerprint"]:
        raise ProjectionError("resolved context capability lock is stale")
    if resolved_context.get("project") != lock["project"]:
        raise ProjectionError("resolved context project does not match capability lock")
    _verify_resolved_context(root, project, resolved_context, runtime=runtime)
    try:
        project_identity = safe_relative_path(resolved_context["project"], label="projection project")
    except (KeyError, PathBoundaryError) as exc:
        raise ProjectionError("resolved context project is not a safe identity") from exc
    if len(project_identity.parts) != 1:
        raise ProjectionError("resolved context project is not a safe identity")
    by_version = _capability_maps(root)
    source_capabilities: list[dict[str, Any]] = []
    selected_index: dict[str, dict[str, Any]] = {}
    for item in sorted(resolved_context.get("selectedCapabilities", []), key=lambda value: value["id"]):
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
    target_pack.parent.mkdir(parents=True, exist_ok=True)
    _recover_projection_swap(
        target_pack,
        runtime=runtime,
        project_id=project_identity.as_posix(),
    )
    token = uuid.uuid4().hex
    pack = target_pack.parent / f".{target_pack.name}.tmp-{token}"
    backup = target_pack.parent / f".{target_pack.name}.backup-{token}"
    journal_path = _projection_swap_journal_path(target_pack)
    pack.mkdir()

    try:
        stable_name = "project-instructions.md" if runtime == "CHATGPT" else "repository-guidance.md"
        (pack / stable_name).write_text(adapter.stable_guidance(root), encoding="utf-8")
        (pack / adapter.context_filename()).write_text(_resolved_context_markdown(resolved_context), encoding="utf-8")
        write_generated_json(pack / "resolved-context.json", resolved_context)
        (pack / "discussion-contract.md").write_text(
            materialize_discussion_contract(root, project, resolved_context), encoding="utf-8"
        )

        omitted_references: list[dict[str, str]] = []
        generated_skills: list[dict[str, str]] = []
        for source in source_capabilities:
            if source["kind"] != "SKILL":
                continue
            capability = by_version[(source["id"], source["version"])]
            if not _can_materialize(capability.asset.get("visibility", "PRIVATE")):
                marker = {"id": source["id"], "reason": "visibility-gate"}
                if marker not in omitted_references:
                    omitted_references.append(marker)
                continue
            name = source["id"].rsplit(":", 1)[-1]
            target = pack / "skills" / name / "SKILL.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_render_skill(capability, selected_index, by_version, omitted_references), encoding="utf-8")
            generated_skills.append(
                {
                    "id": source["id"],
                    "version": source["version"],
                    "contentHash": source["contentHash"],
                    "skillProjectionVersion": AGENT_SKILL_PROJECTION_VERSION,
                    "path": target.relative_to(pack).as_posix(),
                }
            )

        generated_files: list[dict[str, str]] = []
        for path in sorted(p for p in pack.rglob("*") if p.is_file()):
            generated_files.append({"path": path.relative_to(pack).as_posix(), "sha256": file_sha256(path)})
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
        write_generated_json(pack / "projection-manifest.json", manifest)

        journal = {
            "schemaVersion": "projection-swap-transaction/v1",
            "phase": "PREPARED",
            "runtime": runtime,
            "project": project_identity.as_posix(),
            "token": token,
            "hadTarget": target_pack.exists(),
            "temporaryName": pack.name,
            "backupName": backup.name,
        }
        _write_atomic(journal_path, deterministic_json_bytes(journal))
        if journal["hadTarget"]:
            if target_pack.is_symlink() or not target_pack.is_dir():
                raise ProjectionError("unsafe projection target before swap")
            target_pack.replace(backup)
            _fsync_directory(target_pack.parent)
        pack.replace(target_pack)
        _fsync_directory(target_pack.parent)
        journal["phase"] = "COMMITTED"
        _write_atomic(journal_path, deterministic_json_bytes(journal))
        if backup.exists():
            _remove_projection_directory(backup, label="projection backup")
        journal_path.unlink()
        _fsync_directory(journal_path.parent)
        return manifest
    except BaseException:
        if journal_path.exists():
            _recover_projection_swap(
                target_pack,
                runtime=runtime,
                project_id=project_identity.as_posix(),
            )
        elif pack.exists():
            _remove_projection_directory(pack, label="projection temporary")
        raise


def validate_projection_pack(
    repository_root: Path,
    project_root: Path,
    pack_root: Path,
    *,
    runtime: str,
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
    lock, _ = verify_capability_lock(root, project)
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
    _verify_resolved_context(root, project, resolved, runtime=runtime)
    state_path = project / ".agent-evolution/design-state.yaml"
    binding_path = project / ".agent-evolution/capabilities.yaml"
    if resolved.get("projectStateHash") != file_sha256(state_path) or resolved.get("projectBindingHash") != file_sha256(binding_path):
        raise ProjectionError("canonical projection control-plane drift")

    by_version = _capability_maps(root)
    selected_index: dict[str, dict[str, Any]] = {}
    source_capabilities: list[dict[str, Any]] = []
    for item in sorted(resolved.get("selectedCapabilities", []), key=lambda value: value["id"]):
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
    generated_skills: list[dict[str, str]] = []
    for source in source_capabilities:
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
    return manifest, resolved


def check_projection_freshness(
    repository_root: Path,
    project_root: Path,
    *,
    runtime: str,
    authority_snapshot: dict[str, Any] | None = None,
    expected_resolution_id: str | None = None,
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
    try:
        manifest, _ = validate_projection_pack(root, project, pack, runtime=runtime)
    except Exception:
        return ProjectionFreshness(False, ("projection-integrity-drift",))
    reasons: set[str] = set()
    if manifest.get("projectionVersion") != adapter.projection_version:
        reasons.add("projection-version-changed")
    if expected_resolution_id is not None and manifest.get("sourceResolutionId") != expected_resolution_id:
        reasons.add("resolution-context-drift")
    try:
        lock, _ = verify_capability_lock(root, project)
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
        current = by_version.get((source["id"], source["version"]))
        if current is None or current.content_hash != source["contentHash"]:
            reasons.add("source-capability-hash-changed")
    for item in manifest.get("generatedFiles", []):
        path = pack / item["path"]
        if not path.exists() or file_sha256(path) != item["sha256"]:
            reasons.add("generated-file-drift")
    return ProjectionFreshness(not reasons, tuple(sorted(reasons)))
