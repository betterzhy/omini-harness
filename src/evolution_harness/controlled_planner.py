from __future__ import annotations

import copy
import heapq
from pathlib import Path, PurePosixPath
from typing import Any

from .controlled_conflicts import build_conflict_report
from .controlled_inputs import (
    ControlledPlanningError,
    exact_writeset_digest,
    normalize_planning_request,
    parse_rfc3339,
)
from .hashing import canonical_json_bytes, sha256_bytes
from .schema import SchemaStore


_DECISION_SCHEMA = "core/schemas/controlled-authorization-decision.schema.json"
_REPORT_SCHEMA = "core/schemas/controlled-conflict-report.schema.json"
_PLAN_SCHEMA = "core/schemas/controlled-execution-plan.schema.json"
_PROTECTED_ACTION_CLASSES = frozenset(
    {
        "action:database-write",
        "action:migration-apply",
        "action:destructive",
        "action:production-access",
        "action:landing",
        "action:wave-entry",
        "action:push",
        "action:release",
        "action:deploy",
    }
)


def _stable_id(prefix: str, payload: Any) -> str:
    return f"{prefix}:" + sha256_bytes(canonical_json_bytes(payload))[:24]


def _contains_path(prefix: str, path: str) -> bool:
    prefix_parts = PurePosixPath(prefix).parts
    path_parts = PurePosixPath(path).parts
    return path_parts[: len(prefix_parts)] == prefix_parts


def _authorization_reasons(
    descriptor: dict[str, Any], envelope: dict[str, Any], as_of: Any
) -> list[str]:
    reasons: list[str] = []
    if as_of < parse_rfc3339(envelope["issuedAt"]):
        reasons.append("ENVELOPE_NOT_YET_VALID")
    if as_of >= parse_rfc3339(envelope["expiresAt"]):
        reasons.append("ENVELOPE_EXPIRED")
    if descriptor["portfolioId"] != envelope["portfolioId"]:
        reasons.append("PORTFOLIO_NOT_PERMITTED")
    if descriptor["deliveryTrackId"] not in envelope["permittedDeliveryTracks"]:
        reasons.append("DELIVERY_TRACK_NOT_PERMITTED")
    if descriptor["sliceClass"] not in envelope["permittedSliceClasses"]:
        reasons.append("SLICE_CLASS_NOT_PERMITTED")
    if descriptor["authorizationClass"] not in envelope["permittedActionClasses"]:
        reasons.append("ACTION_CLASS_NOT_PERMITTED")
    if (
        descriptor["authorizationClass"] in _PROTECTED_ACTION_CLASSES
        or descriptor["authorizationClass"] in envelope["deniedActions"]
    ):
        reasons.append("ACTION_EXPLICITLY_DENIED")
    declared_writes = descriptor["exactWriteSet"] + descriptor["ephemeralWriteSet"]
    if any(
        not any(_contains_path(prefix, path) for prefix in envelope["permittedPathPrefixes"])
        for path in declared_writes
    ):
        reasons.append("WRITESET_OUTSIDE_PREFIX")
    if descriptor["state"] != "READY":
        reasons.append("SLICE_NOT_READY")
    return sorted(reasons)


def _authorization_decision(
    repository_root: Path, request: dict[str, Any]
) -> dict[str, Any]:
    envelope = request["authorizationEnvelope"]
    as_of = parse_rfc3339(request["asOf"])
    decisions = []
    for descriptor in sorted(request["slices"], key=lambda item: item["sliceId"]):
        reasons = _authorization_reasons(descriptor, envelope, as_of)
        decisions.append(
            {
                "sliceId": descriptor["sliceId"],
                "result": "REJECT" if reasons else "ALLOW",
                "reasons": reasons,
            }
        )
    gate = (
        "NO_GO"
        if as_of < parse_rfc3339(envelope["issuedAt"])
        or as_of >= parse_rfc3339(envelope["expiresAt"])
        else "PASS"
    )
    decision = {
        "schemaVersion": "controlled-authorization-decision/v1",
        "projectId": request["projectId"],
        "authoritySnapshotFingerprint": request["authoritySnapshot"]["snapshotFingerprint"],
        "envelopeId": envelope["envelopeId"],
        "envelopeDigest": envelope["envelopeDigest"],
        "asOf": request["asOf"],
        "decisions": decisions,
        "gate": gate,
    }
    decision["authorizationDecisionId"] = _stable_id("authorization-decision", decision)
    SchemaStore(repository_root).validate(_DECISION_SCHEMA, decision)
    return decision


def build_authorization_decision(
    repository_root: Path, request: dict[str, Any]
) -> dict[str, Any]:
    """Return an explicit-time authorization decision for a normalized request."""
    normalized = normalize_planning_request(repository_root, request)
    return _authorization_decision(repository_root, normalized)


def _dependency_depths(descriptors: list[dict[str, Any]]) -> dict[str, int]:
    by_id = {item["sliceId"]: item for item in descriptors}
    dependents = {slice_id: [] for slice_id in by_id}
    remaining_dependencies: dict[str, int] = {}
    for descriptor in descriptors:
        for dependency_id in descriptor["dependencySet"]:
            if dependency_id not in by_id:
                raise ControlledPlanningError(
                    "UNKNOWN_DEPENDENCY",
                    f"unknown dependency {dependency_id} for {descriptor['sliceId']}",
                )
            dependents[dependency_id].append(descriptor["sliceId"])
        remaining_dependencies[descriptor["sliceId"]] = len(
            descriptor["dependencySet"]
        )

    for dependent_ids in dependents.values():
        dependent_ids.sort()
    ready = [
        slice_id
        for slice_id, count in remaining_dependencies.items()
        if count == 0
    ]
    heapq.heapify(ready)
    depths = {slice_id: 0 for slice_id in by_id}
    processed = 0
    while ready:
        slice_id = heapq.heappop(ready)
        processed += 1
        for dependent_id in dependents[slice_id]:
            depths[dependent_id] = max(
                depths[dependent_id], depths[slice_id] + 1
            )
            remaining_dependencies[dependent_id] -= 1
            if remaining_dependencies[dependent_id] == 0:
                heapq.heappush(ready, dependent_id)

    if processed != len(by_id):
        cycle_anchor = min(
            slice_id
            for slice_id, count in remaining_dependencies.items()
            if count > 0
        )
        raise ControlledPlanningError(
            "DEPENDENCY_CYCLE",
            f"dependency cycle prevents ordering at {cycle_anchor}",
        )
    return depths


def _execution_requirements(
    envelope: dict[str, Any], proposed_descriptors: list[dict[str, Any]]
) -> dict[str, Any]:
    required_gates = list(envelope["requiredGates"])
    reviewers = set(envelope["requiredReviewers"])
    slice_requirements = []
    for descriptor in sorted(proposed_descriptors, key=lambda item: item["sliceId"]):
        for gate in descriptor["requiredGates"]:
            if gate not in required_gates:
                required_gates.append(gate)
        reviewers.add(descriptor["reviewPolicy"]["reviewerRole"])
        slice_requirements.append(
            {
                "sliceId": descriptor["sliceId"],
                "requiredGates": list(descriptor["requiredGates"]),
                "reviewPolicy": copy.deepcopy(descriptor["reviewPolicy"]),
            }
        )
    return {
        "requiredTests": list(envelope["requiredTests"]),
        "requiredGates": required_gates,
        "requiredReviewers": sorted(reviewers),
        "minimumReviewVerdict": envelope["minimumReviewVerdict"],
        "sliceRequirements": slice_requirements,
    }


def build_provisional_execution_plan(
    repository_root: Path, request: dict[str, Any]
) -> dict[str, Any]:
    """Build deterministic coordinator inputs without admitting or executing work."""
    normalized = normalize_planning_request(repository_root, request)
    descriptors = normalized["slices"]
    by_id = {item["sliceId"]: item for item in descriptors}
    depths = _dependency_depths(descriptors)

    conflict_report = build_conflict_report(
        repository_root,
        project_id=normalized["projectId"],
        authority_snapshot_fingerprint=normalized["authoritySnapshot"]["snapshotFingerprint"],
        conflict_policy_version=normalized["conflictPolicyVersion"],
        descriptors=descriptors,
    )
    decision = _authorization_decision(repository_root, normalized)
    decision_by_id = {item["sliceId"]: item for item in decision["decisions"]}
    cluster_by_slice = {
        slice_id: cluster["clusterId"]
        for cluster in conflict_report["clusters"]
        for slice_id in cluster["sliceIds"]
    }

    blocked = []
    rejected = []
    eligible = []
    for descriptor in descriptors:
        entry = decision_by_id[descriptor["sliceId"]]
        non_readiness_only = entry["reasons"] == ["SLICE_NOT_READY"]
        if entry["result"] == "REJECT" and not non_readiness_only:
            rejected.append({"sliceId": descriptor["sliceId"], "reasons": entry["reasons"]})
            continue
        if descriptor["state"] != "READY":
            blocked.append(
                {"sliceId": descriptor["sliceId"], "reasons": ["SLICE_NOT_READY"]}
            )
            continue
        if any(by_id[item]["state"] != "CLOSED" for item in descriptor["dependencySet"]):
            blocked.append(
                {"sliceId": descriptor["sliceId"], "reasons": ["DEPENDENCY_NOT_CLOSED"]}
            )
            continue
        eligible.append(descriptor)

    lane_cap = min(normalized["authorizationEnvelope"]["maxParallelLanes"], 3)
    proposed_descriptors = []
    queued = []
    occupied_clusters: set[str] = set()
    for descriptor in sorted(
        eligible,
        key=lambda item: (item["priority"], depths[item["sliceId"]], item["sliceId"]),
    ):
        cluster_id = cluster_by_slice[descriptor["sliceId"]]
        if cluster_id in occupied_clusters:
            queued.append(
                {"sliceId": descriptor["sliceId"], "reasons": ["CONFLICT_CLUSTER_BUSY"]}
            )
        elif len(proposed_descriptors) >= lane_cap:
            queued.append(
                {"sliceId": descriptor["sliceId"], "reasons": ["PROJECT_CAPACITY_LIMIT"]}
            )
        else:
            proposed_descriptors.append(descriptor)
            occupied_clusters.add(cluster_id)

    envelope = normalized["authorizationEnvelope"]
    plan = {
        "schemaVersion": "controlled-execution-plan/v1",
        "projectId": normalized["projectId"],
        "batchBaseCommit": normalized["batchBaseCommit"],
        "authoritySnapshotFingerprint": normalized["authoritySnapshot"]["snapshotFingerprint"],
        "contractRegistryDigest": normalized["contractRegistryDigest"],
        "dependencyGraphDigest": normalized["dependencyGraphDigest"],
        "authorizationEnvelopeDigest": envelope["envelopeDigest"],
        "conflictPolicyVersion": normalized["conflictPolicyVersion"],
        "harnessVersion": normalized["harnessVersion"],
        "asOf": normalized["asOf"],
        "conflictReportId": conflict_report["conflictReportId"],
        "authorizationDecisionId": decision["authorizationDecisionId"],
        "provisional": True,
        "requiresCoordinatorRecheck": True,
        "projectLaneCap": lane_cap,
        "proposedAdmissions": [
            {
                "sliceId": item["sliceId"],
                "conflictClusterId": cluster_by_slice[item["sliceId"]],
                "descriptorDigest": item["descriptorDigest"],
                "exactWriteSetDigest": exact_writeset_digest(item),
            }
            for item in sorted(proposed_descriptors, key=lambda item: item["sliceId"])
        ],
        "queued": sorted(queued, key=lambda item: item["sliceId"]),
        "blocked": sorted(blocked, key=lambda item: item["sliceId"]),
        "rejected": sorted(rejected, key=lambda item: item["sliceId"]),
        "executionRequirements": _execution_requirements(envelope, proposed_descriptors),
        "mandatoryStopConditions": list(envelope["stopConditions"]),
    }
    plan["batchPlanId"] = _stable_id("batch-plan", plan)

    store = SchemaStore(repository_root)
    store.validate(_REPORT_SCHEMA, conflict_report)
    store.validate(_DECISION_SCHEMA, decision)
    store.validate(_PLAN_SCHEMA, plan)
    return {
        "conflictReport": conflict_report,
        "authorizationDecision": decision,
        "executionPlan": plan,
    }
