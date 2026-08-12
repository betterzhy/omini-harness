from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .catalog import build_design_active_catalog
from .hashing import canonical_json_bytes, sha256_bytes
from .registry import build_design_registry
from .schema import SchemaStore


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_project_state(repository_root: Path, project_root: Path) -> dict[str, Any]:
    root = Path(repository_root)
    path = Path(project_root) / ".agent-evolution" / "design-state.yaml"
    value = _load_yaml(path)
    SchemaStore(root).validate("core/schemas/project-design-state.schema.json", value)
    topic_ids = [item["topicId"] for item in value["topics"]]
    if len(topic_ids) != len(set(topic_ids)):
        raise ValueError("project design state contains duplicate topic ids")
    return value


def load_project_binding(repository_root: Path, project_root: Path) -> dict[str, Any]:
    root = Path(repository_root)
    path = Path(project_root) / ".agent-evolution" / "capabilities.yaml"
    value = _load_yaml(path)
    SchemaStore(root).validate("core/schemas/project-capability-binding.schema.json", value)
    return value


def load_profile(repository_root: Path, profile_id: str) -> dict[str, Any]:
    root = Path(repository_root)
    for path in sorted((root / "runtime" / "profiles").glob("*.yaml")):
        value = _load_yaml(path)
        if value.get("id") == profile_id:
            if value.get("schemaVersion") != "capability-profile/v1" or not isinstance(value.get("capabilities"), list):
                raise ValueError(f"invalid profile: {profile_id}")
            return value
    raise KeyError(f"profile not found: {profile_id}")


def bound_capability_reasons(repository_root: Path, project_root: Path) -> dict[str, list[str]]:
    root = Path(repository_root)
    binding = load_project_binding(root, project_root)
    disabled = set(binding["disabledCapabilities"])
    reasons: dict[str, list[str]] = {}
    for profile_id in binding["profiles"]:
        for capability_id in load_profile(root, profile_id)["capabilities"]:
            reasons.setdefault(capability_id, []).append(f"profile:{profile_id}")
    for capability_id in binding["capabilities"]:
        reasons.setdefault(capability_id, []).append("explicit-binding")
    for capability_id in binding["extensions"]:
        reasons.setdefault(capability_id, []).append("project-extension")
    return {capability_id: reason for capability_id, reason in reasons.items() if capability_id not in disabled}


def build_capability_lock(repository_root: Path, project_root: Path, *, write: bool = False) -> dict[str, Any]:
    root = Path(repository_root)
    project = Path(project_root)
    binding = load_project_binding(root, project)
    reasons = bound_capability_reasons(root, project)
    catalog = build_design_active_catalog(root, write=False)
    by_id = {entry["id"]: entry for entry in catalog["entries"]}
    capability_sources: list[dict[str, str]] = []
    for capability_id in sorted(reasons):
        entry = by_id.get(capability_id)
        if entry is None:
            raise ValueError(f"bound capability is not active/valid/current: {capability_id}")
        capability_sources.append(
            {
                "capabilityId": capability_id,
                "resolvedVersion": entry["version"],
                "contentHash": entry["contentHash"],
            }
        )
    source_revision = capability_lock_source_revision(capability_sources)
    capabilities = [
        {
            **source,
            "sourceHarnessRevision": source_revision,
            "resolvedBecause": reasons[source["capabilityId"]],
        }
        for source in capability_sources
    ]
    result: dict[str, Any] = {
        "schemaVersion": "capability-lock/v1",
        "project": load_project_state(root, project)["project"],
        "sourceHarnessRevision": source_revision,
        "disabledCapabilities": sorted(binding["disabledCapabilities"]),
        "capabilities": capabilities,
    }
    result["lockFingerprint"] = capability_lock_fingerprint(result)
    SchemaStore(root).validate("core/schemas/capability-lock.schema.json", result)
    if write:
        path = project / ".agent-evolution" / "capabilities.lock.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return result


def capability_lock_fingerprint(lock: dict[str, Any]) -> str:
    payload = {key: value for key, value in lock.items() if key != "lockFingerprint"}
    return "sha256:" + sha256_bytes(canonical_json_bytes(payload))


def capability_lock_source_revision(capabilities: list[dict[str, Any]]) -> str:
    sources = sorted(
        [
            {
                "capabilityId": item["capabilityId"],
                "resolvedVersion": item["resolvedVersion"],
                "contentHash": item["contentHash"],
            }
            for item in capabilities
        ],
        key=lambda item: item["capabilityId"],
    )
    return "content-sha256:" + sha256_bytes(canonical_json_bytes(sources))


def load_capability_lock(repository_root: Path, project_root: Path) -> dict[str, Any]:
    root = Path(repository_root)
    project = Path(project_root)
    path = project / ".agent-evolution" / "capabilities.lock.yaml"
    if not path.exists():
        raise ValueError(f"capability lock missing: {path}")
    lock = _load_yaml(path)
    SchemaStore(root).validate("core/schemas/capability-lock.schema.json", lock)
    if lock["lockFingerprint"] != capability_lock_fingerprint(lock):
        raise ValueError("capability lock fingerprint mismatch")
    return lock


def verify_capability_lock(
    repository_root: Path,
    project_root: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    root = Path(repository_root)
    project = Path(project_root)
    lock = load_capability_lock(root, project)
    state = load_project_state(root, project)
    binding = load_project_binding(root, project)
    reasons = bound_capability_reasons(root, project)
    if lock["project"] != state["project"]:
        raise ValueError("capability lock project does not match project state")
    if lock["disabledCapabilities"] != sorted(binding["disabledCapabilities"]):
        raise ValueError("capability lock binding disabledCapabilities drift")
    locked_items = {item["capabilityId"]: item for item in lock["capabilities"]}
    if len(locked_items) != len(lock["capabilities"]):
        raise ValueError("capability lock contains duplicate capability ids")
    if set(locked_items) != set(reasons):
        raise ValueError("capability lock binding capability set drift")
    expected_source_revision = capability_lock_source_revision(lock["capabilities"])
    if lock["sourceHarnessRevision"] != expected_source_revision:
        raise ValueError("capability lock source revision is not reproducible from exact sources")

    registry = build_design_registry(root, write=False)
    by_version = {(entry["id"], entry["version"]): entry for entry in registry["entries"]}
    verified: dict[str, dict[str, Any]] = {}
    for capability_id, item in locked_items.items():
        if item["sourceHarnessRevision"] != lock["sourceHarnessRevision"]:
            raise ValueError(f"capability lock source revision mismatch: {capability_id}")
        if sorted(item["resolvedBecause"]) != sorted(reasons[capability_id]):
            raise ValueError(f"capability lock binding reasons drift: {capability_id}")
        entry = by_version.get((capability_id, item["resolvedVersion"]))
        if entry is None:
            raise ValueError(f"capability lock references missing version: {capability_id}@{item['resolvedVersion']}")
        if entry["contentHash"] != item["contentHash"]:
            raise ValueError(f"capability lock content hash drift: {capability_id}")
        if entry["lifecycle"] in {"DEPRECATED", "RETIRED"} or entry["validity"] != "VALID":
            raise ValueError(f"capability lock references unusable capability: {capability_id}")
        verified[capability_id] = entry
    return lock, verified
