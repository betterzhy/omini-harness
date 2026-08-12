from __future__ import annotations

from pathlib import Path
from typing import Any

from .catalog import build_engineering_active_catalog
from .generated import deterministic_json_bytes
from .registry import build_engineering_registry


def validate_engineering(repository_root: Path) -> dict[str, Any]:
    root = Path(repository_root)
    issues: list[dict[str, str]] = []
    try:
        registry = build_engineering_registry(root, write=False)
        ids = {entry["id"] for entry in registry["entries"]}
        for entry in registry["entries"]:
            for targets in entry.get("relationships", {}).values():
                if isinstance(targets, list):
                    for target in targets:
                        if target not in ids:
                            issues.append({"code": "BROKEN_REFERENCE", "message": f"target not found: {target}"})
    except Exception as exc:
        registry = {"entries": []}
        issues.append({"code": "ENGINEERING_INVALID", "message": str(exc)})
    return {
        "engineeringDomain": "PASS" if not issues else "FAIL",
        "issues": issues,
        "registeredAssetCount": len(registry["entries"]),
    }


def engineering_doctor(repository_root: Path, *, ci: bool = False) -> dict[str, Any]:
    root = Path(repository_root)
    report = validate_engineering(root)
    if ci:
        expected_registry = deterministic_json_bytes(build_engineering_registry(root, write=False))
        expected_catalog = deterministic_json_bytes(build_engineering_active_catalog(root, write=False))
        for name, path, expected in [
            ("registry", root / "engineering/generated/registry.json", expected_registry),
            ("active-catalog", root / "engineering/generated/active-catalog.json", expected_catalog),
        ]:
            if not path.exists() or path.read_bytes() != expected:
                report["issues"].append({"code": "GENERATED_DRIFT", "message": f"{name} is missing or stale"})
        report["engineeringDomain"] = "PASS" if not report["issues"] else "FAIL"
    return report


def resolve_engineering_context(repository_root: Path, *, task_kind: str = "repository-change") -> dict[str, Any]:
    root = Path(repository_root)
    catalog = build_engineering_active_catalog(root, write=False)
    selected = []
    for entry in catalog["entries"]:
        selected.append({"id": entry["id"], "version": entry["version"], "contentHash": entry["contentHash"], "selectedBecause": [f"task-kind:{task_kind}", "active-valid"]})
    return {"schema_version": "engineering-context/v1", "task_kind": task_kind, "selected": selected}
