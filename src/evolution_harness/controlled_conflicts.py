from __future__ import annotations

from itertools import combinations, product
from pathlib import Path, PurePosixPath
from typing import Any

from .hashing import canonical_json_bytes, sha256_bytes
from .schema import SchemaStore


_REPORT_SCHEMA = "core/schemas/controlled-conflict-report.schema.json"
_FOOTPRINT_FIELDS = (
    "ownerSet",
    "factFamilySet",
    "publicContractSet",
    "producerConsumerSet",
    "bindingSet",
    "exactWriteSet",
    "ephemeralWriteSet",
    "sharedArtifactSet",
    "dependencySet",
    "migrationResourceSet",
    "authorityReferences",
)


def _path_overlaps(left: str, right: str) -> bool:
    left_parts = PurePosixPath(left).parts
    right_parts = PurePosixPath(right).parts
    size = min(len(left_parts), len(right_parts))
    return left_parts[:size] == right_parts[:size]


def _stable_id(prefix: str, payload: Any) -> str:
    return f"{prefix}:" + sha256_bytes(canonical_json_bytes(payload))[:24]


def _transitive_closure(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    closure = {node: set(edges) for node, edges in graph.items()}
    for node in list(closure):
        for target in closure[node]:
            closure.setdefault(target, set())
    for pivot in sorted(closure):
        for source in sorted(closure):
            if pivot in closure[source]:
                closure[source].update(closure[pivot])
    return closure


def _sets_overlap(left: dict[str, Any], right: dict[str, Any], field: str) -> bool:
    return bool(set(left[field]).intersection(right[field]))


def _any_path_overlap(left_paths: list[str], right_paths: list[str]) -> bool:
    return any(_path_overlaps(left, right) for left, right in product(left_paths, right_paths))


def _dependency_closure(descriptors: list[dict[str, Any]]) -> dict[str, set[str]]:
    graph = {item["sliceId"]: set(item["dependencySet"]) for item in descriptors}
    return _transitive_closure(graph)


def _owner_closure(descriptors: list[dict[str, Any]]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for descriptor in descriptors:
        for owner in descriptor["ownerSet"]:
            graph.setdefault(owner, set())
        for relation in descriptor["producerConsumerSet"]:
            graph.setdefault(relation["producer"], set()).add(relation["consumer"])
            graph.setdefault(relation["consumer"], set())
    return _transitive_closure(graph)


def _has_path(
    closure: dict[str, set[str]], left_values: list[str], right_values: list[str]
) -> bool:
    return any(right in closure.get(left, set()) for left, right in product(left_values, right_values))


def _is_barrier(descriptor: dict[str, Any], field: str) -> bool:
    if field == "GLOBAL_SHARED_ARTIFACT_BARRIER":
        return any(value.startswith("global:") for value in descriptor["sharedArtifactSet"])
    return bool(descriptor[field])


def _conflict_reasons(
    left: dict[str, Any],
    right: dict[str, Any],
    dependency_closure: dict[str, set[str]],
    owner_closure: dict[str, set[str]],
) -> list[str]:
    reasons: set[str] = set()
    if _sets_overlap(left, right, "ownerSet"):
        reasons.add("SAME_OWNER")
    if _sets_overlap(left, right, "factFamilySet"):
        reasons.add("FACT_FAMILY_OVERLAP")
    if _sets_overlap(left, right, "bindingSet"):
        reasons.add("BINDING_OVERLAP")
    if _any_path_overlap(left["exactWriteSet"], right["exactWriteSet"]):
        reasons.add("EXACT_WRITESET_OVERLAP")
    if (
        _any_path_overlap(left["ephemeralWriteSet"], right["exactWriteSet"])
        or _any_path_overlap(left["exactWriteSet"], right["ephemeralWriteSet"])
        or _any_path_overlap(left["ephemeralWriteSet"], right["ephemeralWriteSet"])
    ):
        reasons.add("EPHEMERAL_WRITESET_OVERLAP")
    if _sets_overlap(left, right, "sharedArtifactSet"):
        reasons.add("SHARED_ARTIFACT_OVERLAP")
    if (
        _any_path_overlap(left["exactWriteSet"], right["authorityReferences"])
        or _any_path_overlap(left["ephemeralWriteSet"], right["authorityReferences"])
        or _any_path_overlap(right["exactWriteSet"], left["authorityReferences"])
        or _any_path_overlap(right["ephemeralWriteSet"], left["authorityReferences"])
    ):
        reasons.add("AUTHORITY_INPUT_WRITE")
    if (
        right["sliceId"] in dependency_closure.get(left["sliceId"], set())
        or left["sliceId"] in dependency_closure.get(right["sliceId"], set())
    ):
        reasons.add("DEPENDENCY_PATH")
    if (
        _has_path(owner_closure, left["ownerSet"], right["ownerSet"])
        or _has_path(owner_closure, right["ownerSet"], left["ownerSet"])
    ):
        reasons.add("PRODUCER_CONSUMER_PATH")
    if _is_barrier(left, "publicContractSet") or _is_barrier(right, "publicContractSet"):
        reasons.add("PUBLIC_CONTRACT_SERIAL_BARRIER")
    if _is_barrier(left, "migrationResourceSet") or _is_barrier(right, "migrationResourceSet"):
        reasons.add("MIGRATION_SERIAL_BARRIER")
    if _is_barrier(left, "GLOBAL_SHARED_ARTIFACT_BARRIER") or _is_barrier(
        right, "GLOBAL_SHARED_ARTIFACT_BARRIER"
    ):
        reasons.add("GLOBAL_SHARED_ARTIFACT_BARRIER")
    return sorted(reasons)


def _footprint(project_id: str, conflict_policy_version: str, descriptor: dict[str, Any]) -> dict[str, Any]:
    item = {"sliceId": descriptor["sliceId"]}
    for field in _FOOTPRINT_FIELDS:
        item[field] = descriptor[field]
    item["conflictFootprintId"] = _stable_id(
        "footprint",
        {
            "projectId": project_id,
            "conflictPolicyVersion": conflict_policy_version,
            **item,
        },
    )
    return item


def _clusters(project_id: str, conflict_policy_version: str, slice_ids: list[str], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    adjacency = {slice_id: set() for slice_id in slice_ids}
    for edge in edges:
        adjacency[edge["leftSliceId"]].add(edge["rightSliceId"])
        adjacency[edge["rightSliceId"]].add(edge["leftSliceId"])
    clusters = []
    remaining = set(slice_ids)
    while remaining:
        start = min(remaining)
        component = {start}
        pending = [start]
        while pending:
            current = pending.pop()
            for neighbor in sorted(adjacency[current] - component):
                component.add(neighbor)
                pending.append(neighbor)
        remaining.difference_update(component)
        member_ids = sorted(component)
        clusters.append({
            "clusterId": _stable_id(
                "conflict-cluster",
                {
                    "projectId": project_id,
                    "conflictPolicyVersion": conflict_policy_version,
                    "sliceIds": member_ids,
                },
            ),
            "sliceIds": member_ids,
        })
    return sorted(clusters, key=lambda item: item["sliceIds"])


def build_conflict_report(
    repository_root: Path,
    *,
    project_id: str,
    authority_snapshot_fingerprint: str,
    conflict_policy_version: str,
    descriptors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a conservative, deterministic conflict graph from normalized descriptors."""
    ordered_descriptors = sorted(descriptors, key=lambda item: item["sliceId"])
    dependency_closure = _dependency_closure(ordered_descriptors)
    owner_closure = _owner_closure(ordered_descriptors)
    edges = []
    for left, right in combinations(ordered_descriptors, 2):
        reasons = _conflict_reasons(left, right, dependency_closure, owner_closure)
        if reasons:
            edges.append({
                "leftSliceId": left["sliceId"],
                "rightSliceId": right["sliceId"],
                "reasons": reasons,
            })
    footprints = [
        _footprint(project_id, conflict_policy_version, descriptor)
        for descriptor in ordered_descriptors
    ]
    clusters = _clusters(
        project_id,
        conflict_policy_version,
        [item["sliceId"] for item in ordered_descriptors],
        edges,
    )
    report = {
        "schemaVersion": "controlled-conflict-report/v1",
        "projectId": project_id,
        "authoritySnapshotFingerprint": authority_snapshot_fingerprint,
        "conflictPolicyVersion": conflict_policy_version,
        "footprints": footprints,
        "edges": edges,
        "clusters": clusters,
    }
    report["conflictReportId"] = _stable_id("conflict-report", report)
    SchemaStore(repository_root).validate(_REPORT_SCHEMA, report)
    return report
