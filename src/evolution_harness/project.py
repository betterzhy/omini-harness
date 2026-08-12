from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .catalog import build_design_active_catalog
from .schema import SchemaStore


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_project_state(repository_root: Path, project_root: Path) -> dict[str, Any]:
    root = Path(repository_root)
    path = Path(project_root) / ".agent-evolution" / "design-state.yaml"
    value = _load_yaml(path)
    SchemaStore(root).validate("core/schemas/project-design-state.schema.json", value)
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
    capabilities: list[dict[str, Any]] = []
    for capability_id in sorted(reasons):
        entry = by_id.get(capability_id)
        if entry is None:
            raise ValueError(f"bound capability is not active/valid/current: {capability_id}")
        capabilities.append(
            {
                "capabilityId": capability_id,
                "resolvedVersion": entry["version"],
                "contentHash": entry["contentHash"],
                "sourceHarnessRevision": catalog["sourceRevision"],
                "resolvedBecause": reasons[capability_id],
            }
        )
    result = {
        "schemaVersion": "capability-lock/v1",
        "project": load_project_state(root, project)["project"],
        "sourceHarnessRevision": catalog["sourceRevision"],
        "disabledCapabilities": sorted(binding["disabledCapabilities"]),
        "capabilities": capabilities,
    }
    if write:
        path = project / ".agent-evolution" / "capabilities.lock.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return result
