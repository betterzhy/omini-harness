from __future__ import annotations

import copy
import json
from pathlib import Path, PurePosixPath
from typing import Any

from .controlled_inputs import (
    ControlledPlanningError,
    normalize_authorization_envelope,
    normalize_planning_request,
    normalize_slice_descriptor,
    parse_rfc3339,
)
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
        or value.startswith("//")
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


def _normalize_acquire_evidence(
    repository_root: Path, command: dict[str, Any]
) -> None:
    try:
        command["planningRequest"] = normalize_planning_request(
            repository_root, command["planningRequest"]
        )
        command["sliceDescriptor"] = normalize_slice_descriptor(
            repository_root, command["sliceDescriptor"]
        )
        command["authorizationEnvelope"] = normalize_authorization_envelope(
            repository_root, command["authorizationEnvelope"]
        )
    except (ControlledPlanningError, SchemaValidationError) as exc:
        code = getattr(exc, "code", "COORDINATOR_COMMAND_INVALID")
        raise ControlledCoordinationError(code, str(exc)) from exc

    request = command["planningRequest"]
    for authority in request["authoritySnapshot"]["authorities"]:
        authority["path"] = _canonical_relative_path(
            authority["path"], "planningRequest.authoritySnapshot.authorities.path"
        )
    for fact_id, fact in request["authoritySnapshot"]["facts"].items():
        fact["sourcePath"] = _canonical_relative_path(
            fact["sourcePath"],
            f"planningRequest.authoritySnapshot.facts.{fact_id}.sourcePath",
        )
    request_authority_ids = [
        item["id"] for item in request["authoritySnapshot"]["authorities"]
    ]
    request_authority_paths = [
        item["path"] for item in request["authoritySnapshot"]["authorities"]
    ]
    if (
        len(request_authority_ids) != len(set(request_authority_ids))
        or len(request_authority_paths) != len(set(request_authority_paths))
    ):
        raise ControlledCoordinationError(
            "AUTHORITY_RECORD_DUPLICATE",
            "planning request authority records must have unique IDs and paths",
        )

    proof = command["admissionAuthorityProof"]
    proof["manifestAuthorityReference"] = _canonical_relative_path(
        proof["manifestAuthorityReference"],
        "admissionAuthorityProof.manifestAuthorityReference",
    )
    binding = proof["binding"]
    binding["originalSourceRoot"] = _canonical_absolute_path(
        binding["originalSourceRoot"],
        "admissionAuthorityProof.binding.originalSourceRoot",
    )
    binding["laneRoot"] = _canonical_absolute_path(
        binding["laneRoot"], "admissionAuthorityProof.binding.laneRoot"
    )


def _validate_planning_request_binding(command: dict[str, Any]) -> None:
    request = command["planningRequest"]
    request_descriptors = {item["sliceId"]: item for item in request["slices"]}
    if (
        request["projectId"] != command["projectId"]
        or request["batchBaseCommit"] != command["expectedLaneBase"]
        or request["authoritySnapshot"] != command["authoritySnapshot"]
        or request["authorizationEnvelope"] != command["authorizationEnvelope"]
        or request["conflictPolicyVersion"] != command["conflictPolicyVersion"]
        or request["asOf"] != command["asOf"]
        or request_descriptors.get(command["sliceId"])
        != command["sliceDescriptor"]
    ):
        raise ControlledCoordinationError(
            "ADMISSION_AUTHORITY_BINDING_MISMATCH",
            "planning request does not bind the acquire evidence",
        )


def _validate_admission_authority(command: dict[str, Any]) -> None:
    snapshot = command["authoritySnapshot"]
    expected_snapshot_fingerprint = _sha256(
        {key: value for key, value in snapshot.items() if key != "snapshotFingerprint"}
    )
    if snapshot["snapshotFingerprint"] != expected_snapshot_fingerprint:
        raise ControlledCoordinationError(
            "ADMISSION_AUTHORITY_BINDING_MISMATCH",
            "authority snapshot fingerprint is not canonical",
        )
    expected_authority_set_digest = _sha256(snapshot["authorities"])
    if snapshot["sourceRevision"]["authoritySetDigest"] != expected_authority_set_digest:
        raise ControlledCoordinationError(
            "ADMISSION_AUTHORITY_BINDING_MISMATCH",
            "authority set digest is not canonical",
        )
    if (
        snapshot["snapshotFingerprint"] != command["authoritySnapshotFingerprint"]
        or snapshot["projectId"] != command["projectId"]
        or snapshot["sourceRevision"]["head"] != command["expectedLaneBase"]
        or snapshot["sourceRevision"]["kind"] != "GIT"
        or snapshot["sourceRevision"]["authoritySetStatus"]
        != "CLEAN_FOR_AUTHORITY_SET"
        or snapshot["gate"] != "PASS"
        or snapshot["conflicts"]
        or snapshot["missingFacts"]
    ):
        raise ControlledCoordinationError(
            "ADMISSION_AUTHORITY_BINDING_MISMATCH",
            "authority snapshot does not bind the acquire command",
        )

    proof = command["admissionAuthorityProof"]
    expected_proof_digest = _sha256(
        {key: value for key, value in proof.items() if key != "proofDigest"}
    )
    if proof["proofDigest"] != expected_proof_digest:
        raise ControlledCoordinationError(
            "ADMISSION_AUTHORITY_BINDING_MISMATCH",
            "admission authority proof digest is not canonical",
        )
    binding = proof["binding"]
    expected_binding = {
        "projectId": command["projectId"],
        "sliceId": command["sliceId"],
        "attemptId": command["attemptId"],
        "originalSourceRoot": command["originalSourceRoot"],
        "laneRoot": command["laneRoot"],
    }
    if binding != expected_binding:
        raise ControlledCoordinationError(
            "ADMISSION_AUTHORITY_BINDING_MISMATCH",
            "admission authority proof does not bind acquire identity",
        )
    fact = snapshot["facts"].get(proof["factId"])
    if not isinstance(fact, dict):
        raise ControlledCoordinationError(
            "ADMISSION_AUTHORITY_BINDING_MISMATCH",
            "project-authorized admission fact is missing",
        )
    expected_fact_value = canonical_json_bytes(binding).decode("utf-8")
    fact_value = fact.get("normalizedValue")
    try:
        admitted_bindings = json.loads(fact_value)
    except (TypeError, ValueError):
        admitted_bindings = None
    admission_matches = (
        fact_value == expected_fact_value
        or (
            isinstance(admitted_bindings, list)
            and canonical_json_bytes(admitted_bindings).decode("utf-8") == fact_value
            and binding in admitted_bindings
        )
    )
    if (
        fact.get("owner") != proof["manifestAuthorityId"]
        or fact.get("sourcePath") != proof["manifestAuthorityReference"]
        or not admission_matches
    ):
        raise ControlledCoordinationError(
            "ADMISSION_AUTHORITY_BINDING_MISMATCH",
            "admission fact is not bound to the planning manifest",
        )
    authority = next(
        (
            item
            for item in snapshot["authorities"]
            if item["path"] == proof["manifestAuthorityReference"]
        ),
        None,
    )
    if (
        authority is None
        or authority["id"] != proof["manifestAuthorityId"]
        or proof["manifestAuthorityDigest"] != "sha256:" + authority["sha256"]
    ):
        raise ControlledCoordinationError(
            "ADMISSION_AUTHORITY_BINDING_MISMATCH",
            "admission authority record is not bound to snapshot",
        )

    def planning_fact_value(fact_id: str) -> str:
        planning_fact = snapshot["facts"].get(fact_id)
        if (
            not isinstance(planning_fact, dict)
            or planning_fact.get("owner") != proof["manifestAuthorityId"]
            or planning_fact.get("sourcePath")
            != proof["manifestAuthorityReference"]
            or not isinstance(planning_fact.get("normalizedValue"), str)
        ):
            raise ControlledCoordinationError(
                "ADMISSION_AUTHORITY_BINDING_MISMATCH",
                f"planning authority fact is not bound: {fact_id}",
            )
        return planning_fact["normalizedValue"]

    def planning_fact_allows(fact_id: str, expected_value: Any) -> bool:
        normalized_value = planning_fact_value(fact_id)
        expected_text = (
            expected_value
            if isinstance(expected_value, str)
            else canonical_json_bytes(expected_value).decode("utf-8")
        )
        if normalized_value == expected_text:
            return True
        try:
            choices = json.loads(normalized_value)
        except (TypeError, ValueError):
            return False
        return (
            isinstance(choices, list)
            and canonical_json_bytes(choices).decode("utf-8") == normalized_value
            and expected_value in choices
        )

    expected_facts = {
        "controlled_planning.authorization_envelope_digest": command["authorizationEnvelope"][
            "envelopeDigest"
        ],
        "controlled_planning.conflict_policy_version": command[
            "conflictPolicyVersion"
        ],
    }
    for fact_id, expected_value in expected_facts.items():
        if not planning_fact_allows(fact_id, expected_value):
            raise ControlledCoordinationError(
                "ADMISSION_AUTHORITY_BINDING_MISMATCH",
                f"planning authority fact changed: {fact_id}",
            )
    request_descriptor_digests = sorted(
        item["descriptorDigest"] for item in command["planningRequest"]["slices"]
    )
    if not planning_fact_allows(
        "controlled_planning.slice_descriptor_digests",
        request_descriptor_digests,
    ):
        raise ControlledCoordinationError(
            "ADMISSION_AUTHORITY_BINDING_MISMATCH",
            "descriptor is not present in authority snapshot facts",
        )


def _validate_plan_binding(repository_root: Path, command: dict[str, Any]) -> None:
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

    action_class = command["sliceDescriptor"]["authorizationClass"]
    if action_class in _PROTECTED_ACTION_CLASSES:
        raise ControlledCoordinationError(
            "PROTECTED_ACTION_DENIED",
            f"protected action cannot be acquired: {action_class}",
        )

    try:
        from .controlled_planner import build_provisional_execution_plan

        rebuilt_bundle = build_provisional_execution_plan(
            repository_root, command["planningRequest"]
        )
    except (ControlledPlanningError, SchemaValidationError) as exc:
        code = getattr(exc, "code", "COORDINATOR_COMMAND_INVALID")
        raise ControlledCoordinationError(code, str(exc)) from exc
    rebuilt_plan = rebuilt_bundle["executionPlan"]
    if canonical_json_bytes(rebuilt_plan) != canonical_json_bytes(plan):
        statuses = (
            rebuilt_plan["rejected"]
            + rebuilt_plan["blocked"]
            + rebuilt_plan["queued"]
        )
        target = next(
            (item for item in statuses if item["sliceId"] == command["sliceId"]),
            None,
        )
        reasons = target["reasons"] if target is not None else ["PLAN_DRIFT"]
        raise ControlledCoordinationError(
            "EXECUTION_PLAN_BINDING_MISMATCH",
            "execution plan differs from Phase 1A replay: " + ",".join(reasons),
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
    descriptor = command["sliceDescriptor"]
    envelope = command["authorizationEnvelope"]
    if (
        descriptor["sliceId"] != command["sliceId"]
        or admission["descriptorDigest"] != descriptor["descriptorDigest"]
        or envelope["projectId"] != command["projectId"]
        or envelope["envelopeDigest"] != command["authorizationEnvelopeDigest"]
    ):
        raise ControlledCoordinationError(
            "EXECUTION_PLAN_BINDING_MISMATCH",
            "descriptor or envelope does not match proposed admission",
        )
    action_class = descriptor["authorizationClass"]
    if (
        action_class not in envelope["permittedActionClasses"]
        or action_class in envelope["deniedActions"]
    ):
        raise ControlledCoordinationError(
            "EXECUTION_PLAN_BINDING_MISMATCH",
            "descriptor action is not permitted by authorization envelope",
        )
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
    footprint_payload = {"sliceId": descriptor["sliceId"]}
    for field in _FOOTPRINT_SET_FIELDS:
        footprint_payload[field] = descriptor[field]
    footprint_payload["producerConsumerSet"] = descriptor["producerConsumerSet"]
    expected_footprint = {
        **footprint_payload,
        "conflictFootprintId": _stable_id(
            "footprint",
            {
                "projectId": command["projectId"],
                "conflictPolicyVersion": command["conflictPolicyVersion"],
                **footprint_payload,
            },
        ),
    }
    if canonical_json_bytes(footprint) != canonical_json_bytes(expected_footprint):
        raise ControlledCoordinationError(
            "EXECUTION_PLAN_BINDING_MISMATCH",
            "full conflict footprint does not match normalized descriptor",
        )


def normalize_acquire_command(
    repository_root: Path, value: dict[str, Any]
) -> dict[str, Any]:
    store = SchemaStore(repository_root)
    _validate_schema(store, _ACQUIRE_SCHEMA, value)
    normalized = copy.deepcopy(value)
    normalized["fullFootprint"] = _normalize_footprint(normalized["fullFootprint"])
    _normalize_acquire_evidence(repository_root, normalized)
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
    _validate_planning_request_binding(normalized)
    _validate_admission_authority(normalized)
    _validate_plan_binding(repository_root, normalized)
    return normalized


def _normalize_process_quiescence(value: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(value)
    normalized["processIds"] = sorted(normalized["processIds"])
    return normalized


def _validate_lifecycle_authority(command: dict[str, Any]) -> None:
    proof = command["lifecycleAuthorityProof"]
    proof["authorityReference"] = _canonical_relative_path(
        proof["authorityReference"], "lifecycleAuthorityProof.authorityReference"
    )
    if proof["reviewerAuthorityReference"] is not None:
        proof["reviewerAuthorityReference"] = _canonical_relative_path(
            proof["reviewerAuthorityReference"],
            "lifecycleAuthorityProof.reviewerAuthorityReference",
        )
    _validate_timestamp(proof["assertedAt"])
    expected_digest = _sha256(
        {key: value for key, value in proof.items() if key != "proofDigest"}
    )
    if proof["proofDigest"] != expected_digest or (
        proof["attemptId"], proof["expectedState"], proof["nextState"]
    ) != (
        command["attemptId"],
        command["expectedState"],
        command["nextState"],
    ) or proof["candidateIdentity"] != command["candidateIdentity"]:
        raise ControlledCoordinationError(
            "LIFECYCLE_AUTHORITY_BINDING_MISMATCH",
            "lifecycle authority proof does not bind the transition",
        )


def _validate_review_evidence(command: dict[str, Any]) -> None:
    evidence = command["reviewEvidence"]
    proof = command["lifecycleAuthorityProof"]
    if command["nextState"] != "REVIEW_GO":
        if evidence is not None or any(
            proof[field] is not None
            for field in (
                "reviewBindingDigest",
                "reviewEvidenceDigest",
                "reviewerId",
                "reviewerAuthorityReference",
                "reviewerAuthorityDigest",
            )
        ):
            raise ControlledCoordinationError(
                "REVIEW_EVIDENCE_UNEXPECTED",
                "review evidence is accepted only for REVIEW_GO",
            )
        return
    if evidence is None:
        raise ControlledCoordinationError(
            "REVIEW_EVIDENCE_REQUIRED",
            "REVIEW_GO requires candidate-bound zero-finding review evidence",
        )
    evidence["reviewerAuthorityReference"] = _canonical_relative_path(
        evidence["reviewerAuthorityReference"],
        "reviewEvidence.reviewerAuthorityReference",
    )
    _validate_timestamp(evidence["reviewedAt"])
    expected_binding_digest = _sha256(
        {
            "candidateIdentity": command["candidateIdentity"],
            "authoritySnapshotFingerprint": command["authoritySnapshotFingerprint"],
            "attemptId": command["attemptId"],
            "reviewerId": evidence["reviewerId"],
            "reviewerAuthorityReference": evidence["reviewerAuthorityReference"],
            "reviewerAuthorityDigest": evidence["reviewerAuthorityDigest"],
        }
    )
    expected_evidence_digest = _sha256(
        {key: value for key, value in evidence.items() if key != "evidenceDigest"}
    )
    if (
        evidence["candidateIdentity"] != command["candidateIdentity"]
        or evidence["reviewBindingDigest"] != expected_binding_digest
        or evidence["evidenceDigest"] != expected_evidence_digest
        or proof["reviewBindingDigest"] != evidence["reviewBindingDigest"]
        or proof["reviewEvidenceDigest"] != evidence["evidenceDigest"]
        or proof["reviewerId"] != evidence["reviewerId"]
        or proof["reviewerAuthorityReference"]
        != evidence["reviewerAuthorityReference"]
        or proof["reviewerAuthorityDigest"] != evidence["reviewerAuthorityDigest"]
    ):
        raise ControlledCoordinationError(
            "REVIEW_EVIDENCE_BINDING_MISMATCH",
            "review evidence does not bind the transition candidate",
        )


def normalize_transition_command(
    repository_root: Path, value: dict[str, Any]
) -> dict[str, Any]:
    store = SchemaStore(repository_root)
    _validate_schema(store, _TRANSITION_SCHEMA, value)
    normalized = copy.deepcopy(value)
    normalized["processQuiescence"] = _normalize_process_quiescence(
        normalized["processQuiescence"]
    )
    normalized["lifecycleAuthorityProof"] = copy.deepcopy(
        normalized["lifecycleAuthorityProof"]
    )
    normalized["reviewEvidence"] = copy.deepcopy(normalized["reviewEvidence"])
    _validate_schema(store, _TRANSITION_SCHEMA, normalized)
    _verify_command_digest(normalized)
    _validate_timestamp(normalized["processQuiescence"]["observedAt"])
    _validate_lifecycle_authority(normalized)

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
    _validate_review_evidence(normalized)
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
