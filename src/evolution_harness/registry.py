from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from .capability_pack_registry import (
    CapabilityVerificationSession,
    build_capability_pack_registry,
)
from .generated import write_generated_json
from .hashing import canonical_json_bytes, file_sha256, sha256_bytes
from .loader import load_capabilities
from .schema import SchemaStore

GENERATOR_VERSION = "0.1.0"


def _semver_tuple(value: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def _revision(entries: list[dict[str, Any]]) -> str:
    return "content-sha256:" + sha256_bytes(canonical_json_bytes(entries))


def build_design_registry(repository_root: Path, *, write: bool = False) -> dict[str, Any]:
    root = Path(repository_root)
    capabilities = load_capabilities(root)
    by_id: dict[str, list[Any]] = defaultdict(list)
    for capability in capabilities:
        by_id[capability.id].append(capability)
    current_versions = {
        capability_id: max(items, key=lambda cap: _semver_tuple(cap.version)).version
        for capability_id, items in by_id.items()
    }
    entries: list[dict[str, Any]] = []
    for capability in sorted(capabilities, key=lambda cap: (cap.id, _semver_tuple(cap.version))):
        asset = capability.asset
        entries.append(
            {
                "domain": "design",
                "id": capability.id,
                "kind": asset["kind"],
                "version": capability.version,
                "title": asset["title"],
                "summary": asset["summary"],
                "location": capability.asset_path.parent.relative_to(root).as_posix(),
                "scope": asset["scope"],
                "lifecycle": asset["lifecycle"],
                "validity": asset["validity"],
                "visibility": asset["visibility"],
                "modelSensitivity": asset["modelSensitivity"],
                "relationships": asset["relationships"],
                "evalBindings": asset.get("evalBindings", []),
                "contentHash": capability.content_hash,
                "isCurrent": capability.version == current_versions[capability.id],
            }
        )
    result = {
        "schemaVersion": "design-registry/v1",
        "generatorVersion": GENERATOR_VERSION,
        "sourceRevision": _revision(entries),
        "entries": entries,
    }
    if write:
        write_generated_json(root / "generated" / "registries" / "design-registry.json", result)
    return result


def build_design_learning_registry(repository_root: Path, *, write: bool = False) -> dict[str, Any]:
    root = Path(repository_root)
    store = SchemaStore(root)
    entries: list[dict[str, Any]] = []
    experiences_root = root / "design" / "learning" / "experiences"
    if experiences_root.exists():
        for path in sorted(experiences_root.glob("*.yaml")):
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            store.validate("design/schemas/experience.schema.json", value)
            entries.append(
                {
                    "domain": "design-learning",
                    "entryType": "EXPERIENCE",
                    "id": value["experienceId"],
                    "location": path.relative_to(root).as_posix(),
                    "designStage": value["designStage"],
                    "triageStatus": value["triageStatus"],
                    "triageDecision": value.get("triageDecision"),
                    "visibility": value["visibility"],
                    "sourceReference": value["source"]["reference"],
                    "contentHash": file_sha256(path),
                }
            )
    candidates_root = root / "design" / "learning" / "candidates"
    if candidates_root.exists():
        for path in sorted(candidates_root.glob("*/candidate.yaml")):
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            store.validate("design/schemas/candidate.schema.json", value)
            entries.append(
                {
                    "domain": "design-learning",
                    "entryType": "CANDIDATE",
                    "id": value["candidateId"],
                    "location": path.parent.relative_to(root).as_posix(),
                    "operation": value["operation"],
                    "targetCapability": value["targetCapability"],
                    "promotionStatus": value["promotionStatus"],
                    "authorityDecision": value["authorityDecision"],
                    "sourceExperiences": value["sourceExperiences"],
                    "contentHash": file_sha256(path),
                }
            )
    entries.sort(key=lambda entry: (entry["entryType"], entry["id"]))
    result = {
        "schemaVersion": "design-learning-registry/v1",
        "generatorVersion": GENERATOR_VERSION,
        "sourceRevision": _revision(entries),
        "entries": entries,
    }
    if write:
        write_generated_json(root / "generated" / "registries" / "design-learning-registry.json", result)
    return result


def _engineering_registrations(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    store = SchemaStore(root)
    values: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((root / "engineering" / "registrations").glob("*.yaml")):
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        store.validate("engineering/schemas/registration.schema.json", value)
        values.append((path, value))
    return values


def build_engineering_registry(repository_root: Path, *, write: bool = False) -> dict[str, Any]:
    root = Path(repository_root)
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for registration_path, registration in _engineering_registrations(root):
        if registration["id"] in seen:
            raise ValueError(f"duplicate engineering registration id: {registration['id']}")
        seen.add(registration["id"])
        artifact = root / registration["location"]["path"]
        if not artifact.exists():
            raise FileNotFoundError(artifact)
        entries.append(
            {
                "domain": "engineering",
                "id": registration["id"],
                "kind": registration["type"].upper(),
                "version": registration.get("artifact_revision", "0.0.0"),
                "title": registration["title"],
                "location": registration["location"]["path"],
                "registrationLocation": registration_path.relative_to(root).as_posix(),
                "scope": registration["scope"],
                "lifecycle": registration["lifecycle"],
                "validity": registration["validity"],
                "relationships": registration["relations"],
                "contentHash": file_sha256(artifact),
            }
        )
    entries.sort(key=lambda entry: entry["id"])
    result = {
        "schema_version": "engineering-registry/v1",
        "generator_version": GENERATOR_VERSION,
        "source_revision": _revision(entries),
        "entries": entries,
    }
    if write:
        write_generated_json(root / "engineering" / "generated" / "registry.json", result)
    return result


def build_all_registries(
    repository_root: Path,
    *,
    write: bool = False,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        "design": build_design_registry(repository_root, write=write),
        "designLearning": build_design_learning_registry(repository_root, write=write),
        "engineering": build_engineering_registry(repository_root, write=write),
        "capabilityPacks": build_capability_pack_registry(
            repository_root,
            write=write,
            verification_session=verification_session,
        ),
    }
