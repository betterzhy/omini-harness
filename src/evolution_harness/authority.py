from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .extractors import extract_values
from .hashing import canonical_json_bytes, file_sha256, sha256_bytes
from .integration import load_integration
from .paths import PathBoundaryError, matches_excluded, resolve_within
from .schema import SchemaStore


class IntegrationAuthorityError(ValueError):
    pass


def _normalize(raw: str, selector: dict[str, Any]) -> str:
    normalization = selector.get("normalization")
    if not normalization:
        return raw
    for rule in normalization["rules"]:
        expected = rule["expected"]
        operator = rule["operator"]
        if (
            (operator == "EXACT" and raw == expected)
            or (operator == "PREFIX" and raw.startswith(expected))
            or (operator == "CONTAINS" and expected in raw)
        ):
            return rule["value"]
    return normalization["default"]


def _source_revision(source_root: Path, authorities: list[dict[str, str]]) -> dict[str, str]:
    try:
        head = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        tree = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD^{tree}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return {"kind": "GIT", "head": head, "tree": tree}
    except (OSError, subprocess.CalledProcessError):
        digest = "content-sha256:" + sha256_bytes(canonical_json_bytes(authorities))
        return {"kind": "CONTENT", "head": digest, "tree": digest}


def build_authority_snapshot(
    repository_root: Path,
    integration_root: Path,
    source_root: Path,
) -> dict[str, Any]:
    repository = Path(repository_root).resolve()
    source = Path(source_root).resolve()
    loaded = load_integration(repository, integration_root)
    config = loaded["config"]
    authority_map = loaded["authorityMap"]
    excluded = list(config["excludedPaths"])

    owners: dict[str, list[str]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for authority in authority_map["authorities"]:
        if authority["id"] in by_id:
            raise IntegrationAuthorityError(f"duplicate authority id: {authority['id']}")
        by_id[authority["id"]] = authority
        if authority["role"] == "DERIVED" and authority["owns"]:
            raise IntegrationAuthorityError("derived authority cannot own facts")
        if set(authority["selectors"]) != set(authority["owns"]):
            raise IntegrationAuthorityError(f"selectors must match owned facts: {authority['id']}")
        for fact_id in authority["owns"]:
            owners.setdefault(fact_id, []).append(authority["id"])

    conflicts: list[dict[str, Any]] = []
    for fact_id, fact_owners in sorted(owners.items()):
        if len(fact_owners) > 1:
            conflicts.append({"type": "MULTIPLE_FACT_OWNERS", "factId": fact_id, "owners": sorted(fact_owners)})

    authority_records: list[dict[str, str]] = []
    facts: dict[str, dict[str, str]] = {}
    missing: set[str] = set()
    for authority in authority_map["authorities"]:
        relative = authority["path"]
        try:
            if matches_excluded(relative, excluded):
                raise IntegrationAuthorityError(f"authority path is excluded: {relative}")
            path = resolve_within(source, relative, must_exist=False, label="authority source path")
        except PathBoundaryError as exc:
            raise IntegrationAuthorityError(str(exc)) from exc
        if not path.exists():
            if authority["required"]:
                conflicts.append({"type": "MISSING_AUTHORITY", "authorityId": authority["id"], "path": relative})
                missing.update(authority["owns"])
            continue
        if not path.is_file():
            raise IntegrationAuthorityError(f"authority source is not a file: {relative}")
        authority_records.append(
            {"id": authority["id"], "path": relative, "role": authority["role"], "sha256": file_sha256(path)}
        )
        selectors = authority["selectors"]
        extracted = extract_values(path, authority["format"], [item["key"] for item in selectors.values()])
        for fact_id in authority["owns"]:
            if len(owners.get(fact_id, [])) != 1:
                continue
            selector = selectors[fact_id]
            values = extracted.get(selector["key"], [])
            if not values:
                if selector["required"]:
                    missing.add(fact_id)
                continue
            if len(values) > 1:
                conflicts.append(
                    {"type": "CONFLICTING_VALUES", "factId": fact_id, "owner": authority["id"], "values": values}
                )
                continue
            raw = values[0]
            facts[fact_id] = {
                "owner": authority["id"],
                "sourcePath": relative,
                "rawValue": raw,
                "normalizedValue": _normalize(raw, selector),
            }

    for fact_id in authority_map["requiredFacts"]:
        if fact_id not in facts:
            missing.add(fact_id)
    payload: dict[str, Any] = {
        "schemaVersion": "authority-snapshot/v1",
        "integrationId": config["id"],
        "projectId": config["projectId"],
        "sourceRevision": _source_revision(source, authority_records),
        "authorities": sorted(authority_records, key=lambda item: item["id"]),
        "facts": {key: facts[key] for key in sorted(facts)},
        "conflicts": sorted(conflicts, key=lambda item: (item["type"], item.get("factId", ""))),
        "missingFacts": sorted(missing),
        "excludedPaths": sorted(excluded),
        "gate": "PASS" if not conflicts and not missing else "NO_GO",
    }
    payload["snapshotFingerprint"] = "sha256:" + sha256_bytes(canonical_json_bytes(payload))
    SchemaStore(repository).validate("core/schemas/authority-snapshot.schema.json", payload)
    return payload
