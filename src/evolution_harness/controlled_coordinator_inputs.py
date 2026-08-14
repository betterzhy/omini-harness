from __future__ import annotations

import copy
from pathlib import Path, PurePosixPath
from typing import Any

from .controlled_inputs import ControlledPlanningError, parse_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes
from .paths import PathBoundaryError, safe_relative_path
from .schema import SchemaStore, SchemaValidationError


_ACQUIRE_SCHEMA = "core/schemas/controlled-coordinator-acquire-command.schema.json"
_TRANSITION_SCHEMA = "core/schemas/controlled-coordinator-transition-command.schema.json"
_OBSERVATION_SCHEMA = "core/schemas/controlled-write-observation-command.schema.json"
_RECOVERY_SCHEMA = "core/schemas/controlled-recovery-command.schema.json"

_FOOTPRINT_SET_FIELDS = (
    "ownerSet",
    "factFamilySet",
    "publicContractSet",
    "bindingSet",
    "exactWriteSet",
    "ephemeralWriteSet",
    "sharedArtifactSet",
    "dependencySet",
    "migrationResourceSet",
    "authorityReferences",
)
_FOOTPRINT_PATH_FIELDS = frozenset(
    {"exactWriteSet", "ephemeralWriteSet", "authorityReferences"}
)
_NORMAL_TRANSITIONS = {
    "PROPOSED": frozenset({"READY"}),
    "READY": frozenset({"ADMITTED"}),
    "ADMITTED": frozenset({"ACTIVE"}),
    "ACTIVE": frozenset({"FIXED_CANDIDATE"}),
    "FIXED_CANDIDATE": frozenset({"REVIEW_GO"}),
    "REVIEW_GO": frozenset({"QUEUED_FOR_INTEGRATION"}),
    "QUEUED_FOR_INTEGRATION": frozenset({"INTEGRATING"}),
    "INTEGRATING": frozenset({"CLOSED"}),
}
_EXCEPTIONAL_STATES = frozenset({"BLOCKED", "NO_GO", "STALE", "CANCELLED"})
_CANDIDATE_STATES = frozenset(
    {
        "FIXED_CANDIDATE",
        "REVIEW_GO",
        "QUEUED_FOR_INTEGRATION",
        "INTEGRATING",
        "CLOSED",
    }
)


class ControlledCoordinationError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _sha256(value: Any) -> str:
    return "sha256:" + sha256_bytes(canonical_json_bytes(value))


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}:" + sha256_bytes(canonical_json_bytes(value))[:24]


def _validate_schema(store: SchemaStore, schema_path: str, value: Any) -> None:
    try:
        store.validate(schema_path, value)
    except (SchemaValidationError, FileNotFoundError) as exc:
        raise ControlledCoordinationError(
            "COORDINATOR_COMMAND_INVALID", str(exc)
        ) from exc


def _canonical_relative_path(value: str, label: str) -> str:
    try:
        normalized = safe_relative_path(value, label=label).as_posix()
    except (PathBoundaryError, TypeError) as exc:
        raise ControlledCoordinationError(
            "UNSAFE_COORDINATOR_PATH", str(exc)
        ) from exc
    if normalized != value:
        raise ControlledCoordinationError(
            "UNSAFE_COORDINATOR_PATH",
            f"noncanonical {label}: {value}",
        )
    return normalized


def _canonical_absolute_path(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise ControlledCoordinationError(
            "UNSAFE_COORDINATOR_PATH", f"{label} must be an absolute path"
        )
    path = PurePosixPath(value)
    normalized = path.as_posix()
    if (
        not path.is_absolute()
        or normalized != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ControlledCoordinationError(
            "UNSAFE_COORDINATOR_PATH", f"noncanonical absolute {label}: {value}"
        )
    return normalized


def _canonical_path_set(values: list[str], label: str) -> list[str]:
    normalized = [_canonical_relative_path(value, label) for value in values]
    if len(normalized) != len(set(normalized)):
        raise ControlledCoordinationError(
            "UNSAFE_COORDINATOR_PATH",
            f"duplicate canonical path in {label}",
        )
    return sorted(normalized)


def _canonical_object_set(
    values: list[dict[str, Any]], *, key: str, label: str
) -> list[dict[str, Any]]:
    identities = [item[key] for item in values]
    if len(identities) != len(set(identities)):
        raise ControlledCoordinationError(
            "COORDINATOR_COMMAND_INVALID", f"duplicate {label} member: {key}"
        )
    return sorted(values, key=lambda item: item[key])


def _normalize_footprint(value: dict[str, Any]) -> dict[str, Any]:
    footprint = copy.deepcopy(value)
    for field in _FOOTPRINT_SET_FIELDS:
        if field in _FOOTPRINT_PATH_FIELDS:
            footprint[field] = _canonical_path_set(footprint[field], field)
        else:
            footprint[field] = sorted(footprint[field])
    footprint["producerConsumerSet"] = sorted(
        footprint["producerConsumerSet"],
        key=lambda item: (item["producer"], item["consumer"]),
    )
    return footprint


def _verify_command_digest(value: dict[str, Any]) -> None:
    expected = _sha256(
        {key: item for key, item in value.items() if key != "commandDigest"}
    )
    if value["commandDigest"] != expected:
        raise ControlledCoordinationError(
            "COMMAND_DIGEST_MISMATCH", "command digest does not match normalized command"
        )


def _validate_timestamp(value: str) -> None:
    try:
        parse_rfc3339(value)
    except ControlledPlanningError as exc:
        raise ControlledCoordinationError(exc.code, str(exc)) from exc


def _validate_plan_binding(command: dict[str, Any]) -> None:
    plan = command["executionPlan"]
    expected_plan_id = _stable_id(
        "batch-plan", {key: value for key, value in plan.items() if key != "batchPlanId"}
    )
    if plan["batchPlanId"] != expected_plan_id:
        raise ControlledCoordinationError(
            "EXECUTION_PLAN_ID_MISMATCH", "execution plan identity is not canonical"
        )

    bindings = {
        "projectId": "projectId",
        "batchPlanId": "batchPlanId",
        "authoritySnapshotFingerprint": "authoritySnapshotFingerprint",
        "authorizationEnvelopeDigest": "authorizationEnvelopeDigest",
        "conflictPolicyVersion": "conflictPolicyVersion",
        "asOf": "asOf",
    }
    for command_field, plan_field in bindings.items():
        if command[command_field] != plan[plan_field]:
            raise ControlledCoordinationError(
                "EXECUTION_PLAN_BINDING_MISMATCH",
                f"{command_field} does not match execution plan",
            )
    if command["expectedLaneBase"] != plan["batchBaseCommit"]:
        raise ControlledCoordinationError(
            "EXECUTION_PLAN_BINDING_MISMATCH",
            "expectedLaneBase does not match execution plan batch base",
        )

    admissions = [
        item
        for item in plan["proposedAdmissions"]
        if item["sliceId"] == command["sliceId"]
    ]
    if len(admissions) != 1:
        rejected = next(
            (
                item
                for item in plan["rejected"]
                if item["sliceId"] == command["sliceId"]
            ),
            None,
        )
        if rejected is None or "ACTION_EXPLICITLY_DENIED" not in rejected["reasons"]:
            raise ControlledCoordinationError(
                "EXECUTION_PLAN_BINDING_MISMATCH",
                "slice is not an authorized proposed admission",
            )
        raise ControlledCoordinationError(
            "PROTECTED_ACTION_DENIED",
            "protected action cannot be acquired",
        )
    admission = admissions[0]
    footprint = command["fullFootprint"]
    if footprint["sliceId"] != command["sliceId"]:
        raise ControlledCoordinationError(
            "EXECUTION_PLAN_BINDING_MISMATCH",
            "full footprint slice does not match command",
        )
    expected_writeset_digest = _sha256(sorted(footprint["exactWriteSet"]))
    if admission["exactWriteSetDigest"] != expected_writeset_digest:
        raise ControlledCoordinationError(
            "EXECUTION_PLAN_BINDING_MISMATCH",
            "full footprint exact WriteSet does not match proposed admission",
        )
    footprint_payload = {
        key: value for key, value in footprint.items() if key != "conflictFootprintId"
    }
    expected_footprint_id = _stable_id(
        "footprint",
        {
            "projectId": command["projectId"],
            "conflictPolicyVersion": command["conflictPolicyVersion"],
            **footprint_payload,
        },
    )
    if footprint["conflictFootprintId"] != expected_footprint_id:
        raise ControlledCoordinationError(
            "CONFLICT_FOOTPRINT_ID_MISMATCH",
            "full conflict footprint identity is not canonical",
        )


def normalize_acquire_command(
    repository_root: Path, value: dict[str, Any]
) -> dict[str, Any]:
    store = SchemaStore(repository_root)
    _validate_schema(store, _ACQUIRE_SCHEMA, value)
    normalized = copy.deepcopy(value)
    normalized["fullFootprint"] = _normalize_footprint(normalized["fullFootprint"])
    normalized["originalSourceRoot"] = _canonical_absolute_path(
        normalized["originalSourceRoot"], "originalSourceRoot"
    )
    normalized["laneRoot"] = _canonical_absolute_path(
        normalized["laneRoot"], "laneRoot"
    )
    _validate_schema(store, _ACQUIRE_SCHEMA, normalized)
    _verify_command_digest(normalized)
    _validate_timestamp(normalized["asOf"])
    _validate_timestamp(normalized["executionPlan"]["asOf"])
    _validate_plan_binding(normalized)
    return normalized


def _normalize_process_quiescence(value: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(value)
    normalized["processIds"] = sorted(normalized["processIds"])
    return normalized


def normalize_transition_command(
    repository_root: Path, value: dict[str, Any]
) -> dict[str, Any]:
    store = SchemaStore(repository_root)
    _validate_schema(store, _TRANSITION_SCHEMA, value)
    normalized = copy.deepcopy(value)
    normalized["processQuiescence"] = _normalize_process_quiescence(
        normalized["processQuiescence"]
    )
    _validate_schema(store, _TRANSITION_SCHEMA, normalized)
    _verify_command_digest(normalized)
    _validate_timestamp(normalized["processQuiescence"]["observedAt"])

    expected = normalized["expectedState"]
    next_state = normalized["nextState"]
    allowed = _NORMAL_TRANSITIONS.get(expected, frozenset())
    if next_state not in allowed and (
        next_state not in _EXCEPTIONAL_STATES
        or expected not in _NORMAL_TRANSITIONS
    ):
        raise ControlledCoordinationError(
            "INVALID_STATE_TRANSITION", f"transition {expected} -> {next_state} is not allowed"
        )
    if next_state in _CANDIDATE_STATES and normalized["candidateIdentity"] is None:
        raise ControlledCoordinationError(
            "CANDIDATE_IDENTITY_REQUIRED",
            f"candidate identity is required for {next_state}",
        )
    return normalized


def normalize_write_observation_command(
    repository_root: Path, value: dict[str, Any]
) -> dict[str, Any]:
    store = SchemaStore(repository_root)
    _validate_schema(store, _OBSERVATION_SCHEMA, value)
    normalized = copy.deepcopy(value)
    normalized["observedPaths"] = _canonical_path_set(
        normalized["observedPaths"], "observedPaths"
    )
    normalized["ephemeralPathsRemoved"] = _canonical_path_set(
        normalized["ephemeralPathsRemoved"], "ephemeralPathsRemoved"
    )
    normalized["processQuiescence"] = _normalize_process_quiescence(
        normalized["processQuiescence"]
    )
    _validate_schema(store, _OBSERVATION_SCHEMA, normalized)
    _verify_command_digest(normalized)
    _validate_timestamp(normalized["processQuiescence"]["observedAt"])
    return normalized


def normalize_recovery_command(
    repository_root: Path, value: dict[str, Any]
) -> dict[str, Any]:
    store = SchemaStore(repository_root)
    _validate_schema(store, _RECOVERY_SCHEMA, value)
    normalized = copy.deepcopy(value)
    normalized["recoveryAuthorityReference"] = _canonical_relative_path(
        normalized["recoveryAuthorityReference"], "recoveryAuthorityReference"
    )
    normalized["processQuiescenceProofs"] = _canonical_object_set(
        normalized["processQuiescenceProofs"],
        key="leaseId",
        label="processQuiescenceProofs",
    )
    normalized["observedWriteSet"] = _canonical_path_set(
        normalized["observedWriteSet"], "observedWriteSet"
    )
    normalized["affectedLeaseDecisions"] = _canonical_object_set(
        normalized["affectedLeaseDecisions"],
        key="leaseId",
        label="affectedLeaseDecisions",
    )
    proof_ids = {item["leaseId"] for item in normalized["processQuiescenceProofs"]}
    decision_ids = {item["leaseId"] for item in normalized["affectedLeaseDecisions"]}
    if proof_ids != decision_ids:
        raise ControlledCoordinationError(
            "RECOVERY_LEASE_SET_MISMATCH",
            "quiescence proofs and affected lease decisions must name the same leases",
        )
    _validate_schema(store, _RECOVERY_SCHEMA, normalized)
    _verify_command_digest(normalized)
    for proof in normalized["processQuiescenceProofs"]:
        _validate_timestamp(proof["observedAt"])
    return normalized
