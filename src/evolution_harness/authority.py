from __future__ import annotations

import hashlib
import os
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
    source_descriptor: int,
    authorities: list[dict[str, str]],
    source_bytes: dict[str, bytes],
) -> dict[str, str]:
    authority_set_digest = "sha256:" + sha256_bytes(canonical_json_bytes(authorities))

    def content_revision() -> dict[str, str]:
        digest = "content-sha256:" + authority_set_digest.removeprefix("sha256:")
        return {
            "kind": "CONTENT",
            "head": digest,
            "tree": digest,
            "authoritySetStatus": "CONTENT_SNAPSHOT",
            "authoritySetDigest": authority_set_digest,
        }

    try:
        os.stat(".git", dir_fd=source_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return content_revision()
    except OSError as exc:
        raise IntegrationAuthorityError(
            "authority Git administration path is unsafe"
        ) from exc

    git_boundary = None
    try:
        from .controlled_write_guard import (
            _close_git_boundary,
            _commit_tree_identity,
            _open_git_boundary,
            _physical_identity,
            _read_git_head,
            _read_git_object,
            _read_tree_entries,
            _verify_git_boundary,
        )

        opened_source = os.fstat(source_descriptor)
        git_boundary = _open_git_boundary(
            source_descriptor,
            source_root,
            _physical_identity(opened_source),
            error_code="AUTHORITY_GIT_VIEW_UNAVAILABLE",
            error_message="Authority Git view is not physically anchored",
        )
        head = _read_git_head(git_boundary)
        tree = _commit_tree_identity(
            _read_git_object(git_boundary, head, expected_type="commit")
        )
        committed_entries = _read_tree_entries(
            git_boundary,
            tree,
            requested_paths=[authority["path"] for authority in authorities],
        )
        clean = True
        for authority in authorities:
            try:
                mode, committed_blob = committed_entries[authority["path"]]
                if mode not in {"100644", "100755"}:
                    raise ValueError("authority is not a committed regular file")
                data = source_bytes[authority["path"]]
                object_bytes = f"blob {len(data)}\0".encode("ascii") + data
                hasher = hashlib.sha1 if len(head) == 40 else hashlib.sha256
                working_blob = hasher(object_bytes).hexdigest()
            except (KeyError, OSError, ValueError):
                clean = False
                continue
            if committed_blob != working_blob:
                clean = False
        _verify_git_boundary(git_boundary)
        if _read_git_head(git_boundary) != head:
            raise OSError("Authority Git HEAD changed during snapshot")
        return {
            "kind": "GIT",
            "head": head,
            "tree": tree,
            "authoritySetStatus": "CLEAN_FOR_AUTHORITY_SET" if clean else "DIRTY_AUTHORITY_SET",
            "authoritySetDigest": authority_set_digest,
        }
    except (OSError, RuntimeError, ValueError) as exc:
        raise IntegrationAuthorityError(
            "authority Git view is not physically anchored"
        ) from exc
    finally:
        if git_boundary is not None:
            _close_git_boundary(git_boundary)


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
    source_revision: dict[str, str]
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
            source_revision = _source_revision(
                source,
                source_filesystem._descriptor,
                authority_records,
                authority_bytes,
            )
    except AnchoredPathError as exc:
        raise IntegrationAuthorityError(f"authority source path contains a symlink or changed during snapshot: {exc}") from exc

    for fact_id in authority_map["requiredFacts"]:
        if fact_id not in facts:
            missing.add(fact_id)
    payload: dict[str, Any] = {
        "schemaVersion": "authority-snapshot/v1",
        "integrationId": config["id"],
        "projectId": config["projectId"],
        "sourceRevision": source_revision,
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
