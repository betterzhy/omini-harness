from __future__ import annotations

import json
import shutil
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .discussion import materialize_discussion_contract
from .generated import write_generated_json
from .hashing import file_sha256
from .loader import load_capabilities
from .project import verify_capability_lock

AGENT_SKILL_PROJECTION_VERSION = "agent-skill-projection/1"
CHATGPT_PROJECTION_VERSION = "chatgpt-project-pack/1"
CODEX_PROJECTION_VERSION = "codex-project-pack/1"
_VISIBILITY_RANK = {"PRIVATE": 0, "PROJECT": 1, "SHARED": 2, "PUBLIC": 3}


class ProjectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectionFreshness:
    fresh: bool
    reasons: tuple[str, ...]


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

    target_pack = root / "generated" / "projections" / runtime.lower() / resolved_context["project"]
    target_pack.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    pack = target_pack.parent / f".{target_pack.name}.tmp-{token}"
    backup = target_pack.parent / f".{target_pack.name}.backup-{token}"
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

        if target_pack.exists():
            target_pack.replace(backup)
        try:
            pack.replace(target_pack)
        except Exception:
            if backup.exists():
                backup.replace(target_pack)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return manifest
    except Exception:
        if pack.exists():
            shutil.rmtree(pack)
        if backup.exists():
            if target_pack.exists():
                shutil.rmtree(target_pack)
            backup.replace(target_pack)
        raise


def check_projection_freshness(
    repository_root: Path,
    project_root: Path,
    *,
    runtime: str,
    authority_snapshot: dict[str, Any] | None = None,
) -> ProjectionFreshness:
    root = Path(repository_root)
    project = Path(project_root)
    try:
        adapter = _adapter(runtime)
    except ProjectionError as exc:
        return ProjectionFreshness(False, (str(exc),))
    # The project identifier is authoritative in design-state, but avoid importing resolver or materializing anything.
    import yaml
    state = yaml.safe_load((project / ".agent-evolution/design-state.yaml").read_text(encoding="utf-8")) or {}
    pack = root / "generated" / "projections" / runtime.lower() / state.get("project", project.name)
    manifest_path = pack / "projection-manifest.json"
    if not manifest_path.exists():
        return ProjectionFreshness(False, ("projection-missing",))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reasons: set[str] = set()
    if manifest.get("projectionVersion") != adapter.projection_version:
        reasons.add("projection-version-changed")
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
