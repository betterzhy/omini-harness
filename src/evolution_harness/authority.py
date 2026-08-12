from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .anchored_fs import AnchoredPathError, AnchoredRoot
from .extractors import extract_values_bytes
from .hashing import canonical_json_bytes, sha256_bytes
from .integration import load_integration
from .paths import PathBoundaryError, matches_excluded, resolve_without_symlinks
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


def _source_revision(
    source_root: Path,
    authorities: list[dict[str, str]],
    source_bytes: dict[str, bytes],
) -> dict[str, str]:
    authority_set_digest = "sha256:" + sha256_bytes(canonical_json_bytes(authorities))
    try:
        git_root = Path(
            subprocess.run(
                ["git", "-C", str(source_root), "rev-parse", "--show-toplevel"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        ).resolve()
        head = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        tree = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", f"{head}^{{tree}}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        clean = True
        for authority in authorities:
            try:
                path = source_root / authority["path"]
                repository_relative = path.relative_to(git_root).as_posix()
                committed_blob = subprocess.run(
                    ["git", "-C", str(git_root), "rev-parse", f"{head}:{repository_relative}"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                working_blob = subprocess.run(
                    ["git", "-C", str(git_root), "hash-object", "--stdin"],
                    check=True,
                    capture_output=True,
                    input=source_bytes[authority["path"]],
                ).stdout.decode("utf-8").strip()
            except (OSError, ValueError, subprocess.CalledProcessError):
                clean = False
                continue
            if committed_blob != working_blob:
                clean = False
        return {
            "kind": "GIT",
            "head": head,
            "tree": tree,
            "authoritySetStatus": "CLEAN_FOR_AUTHORITY_SET" if clean else "DIRTY_AUTHORITY_SET",
            "authoritySetDigest": authority_set_digest,
        }
    except (OSError, subprocess.CalledProcessError):
        digest = "content-sha256:" + authority_set_digest.removeprefix("sha256:")
        return {
            "kind": "CONTENT",
            "head": digest,
            "tree": digest,
            "authoritySetStatus": "CONTENT_SNAPSHOT",
            "authoritySetDigest": authority_set_digest,
        }


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
    authority_bytes: dict[str, bytes] = {}
    try:
        with AnchoredRoot(source) as source_filesystem:
            for authority in authority_map["authorities"]:
                relative = authority["path"]
                try:
                    if matches_excluded(relative, excluded):
                        raise IntegrationAuthorityError(f"authority path is excluded: {relative}")
                    path = resolve_without_symlinks(
                        source, relative, must_exist=False, label="authority source path"
                    )
                    canonical_relative = path.relative_to(source).as_posix()
                    if matches_excluded(canonical_relative, excluded):
                        raise IntegrationAuthorityError(f"authority path is excluded: {relative}")
                except PathBoundaryError as exc:
                    raise IntegrationAuthorityError(str(exc)) from exc
                if not source_filesystem.exists(relative):
                    if authority["required"]:
                        conflicts.append({"type": "MISSING_AUTHORITY", "authorityId": authority["id"], "path": relative})
                        missing.update(authority["owns"])
                    continue
                if not source_filesystem.is_file(relative):
                    raise IntegrationAuthorityError(f"authority source is not a file: {relative}")
                data = source_filesystem.read_bytes(relative)
                authority_bytes[relative] = data
                authority_records.append(
                    {
                        "id": authority["id"],
                        "path": relative,
                        "role": authority["role"],
                        "sha256": sha256_bytes(data),
                    }
                )
                selectors = authority["selectors"]
                extracted = extract_values_bytes(
                    data, authority["format"], [item["key"] for item in selectors.values()]
                )
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
    except AnchoredPathError as exc:
        raise IntegrationAuthorityError(f"authority source path contains a symlink or changed during snapshot: {exc}") from exc

    for fact_id in authority_map["requiredFacts"]:
        if fact_id not in facts:
            missing.add(fact_id)
    payload: dict[str, Any] = {
        "schemaVersion": "authority-snapshot/v1",
        "integrationId": config["id"],
        "projectId": config["projectId"],
        "sourceRevision": _source_revision(source, authority_records, authority_bytes),
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
