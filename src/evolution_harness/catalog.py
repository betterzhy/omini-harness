from __future__ import annotations

from pathlib import Path
from typing import Any

from .generated import write_generated_json
from .hashing import canonical_json_bytes, sha256_bytes
from .registry import GENERATOR_VERSION, build_design_registry, build_engineering_registry


def _source_revision(entries: list[dict[str, Any]]) -> str:
    return "content-sha256:" + sha256_bytes(canonical_json_bytes(entries))


def _design_catalog_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain": "design",
        "id": entry["id"],
        "kind": entry["kind"],
        "version": entry["version"],
        "title": entry["title"],
        "summary": entry["summary"],
        "scope": entry["scope"],
        "runtimeCompatibility": entry["scope"].get("runtime", []),
        "relationships": entry["relationships"],
        "contentHash": entry["contentHash"],
        "location": entry["location"],
        "visibility": entry["visibility"],
        "modelSensitivity": entry["modelSensitivity"],
    }


def build_design_active_catalog(repository_root: Path, *, write: bool = False) -> dict[str, Any]:
    root = Path(repository_root)
    registry = build_design_registry(root, write=False)
    current = [entry for entry in registry["entries"] if entry["isCurrent"]]
    eligible = [entry for entry in current if entry["lifecycle"] == "ACTIVE" and entry["validity"] == "VALID"]
    superseded_ids: set[str] = set()
    for entry in eligible:
        superseded_ids.update(entry.get("relationships", {}).get("supersedes", []))
    entries = [_design_catalog_entry(entry) for entry in eligible if entry["id"] not in superseded_ids]
    entries.sort(key=lambda entry: entry["id"])
    result = {
        "schemaVersion": "design-active-catalog/v1",
        "generatorVersion": GENERATOR_VERSION,
        "sourceRevision": _source_revision(entries),
        "entries": entries,
    }
    if write:
        write_generated_json(root / "generated" / "catalogs" / "design-active-catalog.json", result)
    return result


def build_engineering_active_catalog(repository_root: Path, *, write: bool = False) -> dict[str, Any]:
    root = Path(repository_root)
    registry = build_engineering_registry(root, write=False)
    entries = [entry.copy() for entry in registry["entries"] if entry["lifecycle"] == "ACTIVE" and entry["validity"] == "VALID"]
    entries.sort(key=lambda entry: entry["id"])
    result = {
        "schema_version": "engineering-active-catalog/v1",
        "generator_version": GENERATOR_VERSION,
        "source_revision": _source_revision(entries),
        "entries": entries,
    }
    if write:
        write_generated_json(root / "engineering" / "generated" / "active-catalog.json", result)
    return result


def build_all_catalogs(repository_root: Path, *, write: bool = False) -> dict[str, dict[str, Any]]:
    root = Path(repository_root)
    design = build_design_active_catalog(root, write=write)
    engineering = build_engineering_active_catalog(root, write=write)
    entries = sorted([*design["entries"], *engineering["entries"]], key=lambda entry: (entry["domain"], entry["id"]))
    unified = {
        "schemaVersion": "unified-active-catalog/v1",
        "generatorVersion": GENERATOR_VERSION,
        "sourceRevision": _source_revision(entries),
        "entries": entries,
    }
    if write:
        write_generated_json(root / "generated" / "catalogs" / "unified-active-catalog.json", unified)
    return {"design": design, "engineering": engineering, "unified": unified}
