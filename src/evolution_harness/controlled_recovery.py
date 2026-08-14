from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .controlled_coordinator import (
    _current_authority_record,
    _journal_digest,
    _read_current_authority_bytes,
    _rebuild_transition_snapshot,
    _stable_id,
    _validate_lane_physical_identity,
    _verify_sshsig_signature,
    resolve_project_execution_identity,
)
from .controlled_coordinator_inputs import (
    ControlledCoordinationError,
    normalize_recovery_command,
    normalize_write_observation_command,
)
from .coordinator_state import CoordinatorStateStore
from .hashing import canonical_json_bytes


_RECOVERY_SIGNATURE_NAMESPACE = "agent-evolution-controlled-recovery-v1"


def _path_is_within(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _paths_overlap(left: str, right: str) -> bool:
    return _path_is_within(left, right) or _path_is_within(right, left)


def _recoverable_leases(journal: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        lease
        for lease in journal["leases"]
        if lease["released"] is False and lease["state"] != "CLOSED"
    ]


def _acquire_command_for(
    journal: dict[str, Any], lease: dict[str, Any]
) -> dict[str, Any]:
    matches = [
        receipt["evidence"]["command"]
        for receipt in journal["receipts"]
        if receipt["receiptType"] == "ACQUIRE"
        and receipt["evidence"]["command"]["batchPlanId"] == lease["batchPlanId"]
        and receipt["evidence"]["command"]["sliceId"] == lease["sliceId"]
        and receipt["evidence"]["command"]["attemptId"] == lease["attemptId"]
    ]
    if len(matches) != 1:
        raise ControlledCoordinationError(
            "COORDINATOR_STATE_CORRUPT",
            "recoverable lease has no unique Acquire authority command",
        )
    return matches[0]


def _affected_decisions(
    journal: dict[str, Any], observed_write_set: list[str]
) -> list[dict[str, str]]:
    decisions = []
    for lease in _recoverable_leases(journal):
        acquire = _acquire_command_for(journal, lease)
        authority_paths = sorted(
            {
                *acquire["sliceDescriptor"]["authorityReferences"],
                *(
                    authority["path"]
                    for authority in acquire["authoritySnapshot"]["authorities"]
                ),
            }
        )
        footprint_paths = [
            *lease["fullFootprint"]["exactWriteSet"],
            *lease["fullFootprint"]["ephemeralWriteSet"],
        ]
        authority_affected = any(
            _paths_overlap(observed, authority)
            for observed in observed_write_set
            for authority in authority_paths
        )
        writeset_overlap = any(
            _paths_overlap(observed, declared)
            for observed in observed_write_set
            for declared in footprint_paths
        )
        if authority_affected:
            decision, reason = "STALE", "AUTHORITY_AFFECTED"
        elif writeset_overlap:
            decision, reason = "STALE", "WRITESET_OVERLAP"
        else:
            decision, reason = "CANCELLED", "PROJECT_RECOVERY"
        decisions.append(
            {
                "leaseId": lease["leaseId"],
                "decision": decision,
                "reason": reason,
            }
        )
    return sorted(decisions, key=lambda item: item["leaseId"])


def _observation_result(receipt: dict[str, Any]) -> dict[str, Any]:
    evidence = receipt["evidence"]
    return {
        "receiptId": receipt["receiptId"],
        "journalVersion": receipt["nextJournalVersion"],
        "recoveryState": evidence["recoveryState"],
        "observedWriteSet": copy.deepcopy(evidence["observedWriteSet"]),
        "revokedLeaseIds": copy.deepcopy(evidence["revokedLeaseIds"]),
        "affectedLeaseDecisions": copy.deepcopy(
            evidence["affectedLeaseDecisions"]
        ),
    }


def _recovery_signature_payload(command: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in command.items()
        if key not in {"signature", "commandDigest"}
    }


def _recovery_result(receipt: dict[str, Any]) -> dict[str, Any]:
    evidence = receipt["evidence"]
    return {
        "receiptId": receipt["receiptId"],
        "journalVersion": receipt["nextJournalVersion"],
        "recoveryState": evidence["recoveryState"],
        "observedWriteSet": copy.deepcopy(evidence["observedWriteSet"]),
        "releasedLeaseIds": copy.deepcopy(evidence["revokedLeaseIds"]),
        "affectedLeaseDecisions": copy.deepcopy(
            evidence["affectedLeaseDecisions"]
        ),
    }


def quarantine_observed_writes_locked(
    store: CoordinatorStateStore,
    journal: dict[str, Any],
    command: dict[str, Any],
    observed_paths: list[str],
) -> dict[str, Any]:
    """Persist a complete breach while the caller still owns the project lock."""
    current = copy.deepcopy(journal)
    exact_replay = next(
        (
            receipt
            for receipt in current["receipts"]
            if receipt["receiptType"] == "WRITE_OBSERVATION"
            and receipt["commandDigest"] == command["commandDigest"]
            and canonical_json_bytes(receipt["evidence"]["command"])
            == canonical_json_bytes(command)
        ),
        None,
    )
    if exact_replay is not None:
        return _observation_result(exact_replay)
    conflicting = next(
        (
            receipt
            for receipt in current["receipts"]
            if receipt["receiptType"] == "WRITE_OBSERVATION"
            and receipt["evidence"]["command"]["leaseId"] == command["leaseId"]
            and receipt["evidence"]["command"]["fencingToken"]
            == command["fencingToken"]
            and receipt["evidence"]["command"]["beforeInventoryDigest"]
            == command["beforeInventoryDigest"]
        ),
        None,
    )
    if conflicting is not None:
        raise ControlledCoordinationError(
            "WRITE_OBSERVATION_IDEMPOTENCY_CONFLICT",
            "the observation identity is already bound to another payload",
        )
    if current["recoveryState"] not in {"CLEAR", "PROJECT_WRITESET_RECOVERY"}:
        raise ControlledCoordinationError(
            "COORDINATOR_RECOVERY_REQUIRED",
            "state recovery must close before WriteSet quarantine",
        )
    lease = next(
        (item for item in current["leases"] if item["leaseId"] == command["leaseId"]),
        None,
    )
    if lease is None:
        raise ControlledCoordinationError(
            "COORDINATOR_LEASE_NOT_FOUND", "observation lease is not durable"
        )
    if lease["fencingToken"] != command["fencingToken"]:
        raise ControlledCoordinationError(
            "STALE_FENCING_TOKEN", "observation fencing token is not current"
        )
    if lease["released"]:
        raise ControlledCoordinationError(
            "TERMINAL_LEASE_IMMUTABLE", "released lease cannot report a new breach"
        )
    prior_evidence = (
        current.get("recoveryEvidence")
        if current["recoveryState"] == "PROJECT_WRITESET_RECOVERY"
        else None
    )
    prior_paths = (
        [] if not isinstance(prior_evidence, dict) else prior_evidence["observedWriteSet"]
    )
    observed_write_set = sorted({*prior_paths, *observed_paths})
    recoverable = _recoverable_leases(current)
    revoked_ids = sorted(lease["leaseId"] for lease in recoverable)
    decisions = _affected_decisions(current, observed_write_set)
    previously_revoked = set(
        []
        if not isinstance(prior_evidence, dict)
        else prior_evidence["revokedLeaseIds"]
    )
    newly_revoked = [item for item in recoverable if item["leaseId"] not in previously_revoked]
    for affected in recoverable:
        affected["recoveryStatus"] = "PROJECT_WRITESET_RECOVERY"
    current["nextFencingToken"] = max(
        current["nextFencingToken"] + len(newly_revoked),
        max((item["fencingToken"] for item in recoverable), default=0) + 1,
    )
    current["recoveryState"] = "PROJECT_WRITESET_RECOVERY"
    current["recoveryEvidence"] = {
        "observedWriteSet": observed_write_set,
        "revokedLeaseIds": revoked_ids,
        "affectedLeaseDecisions": decisions,
        "quarantineCommand": copy.deepcopy(command),
        "recoveryCommand": None,
    }
    previous_version = current["journalVersion"]
    next_version = previous_version + 1
    current["journalVersion"] = next_version
    receipt = {
        "schemaVersion": "controlled-coordinator-receipt/v1",
        "receiptId": _stable_id(
            "coordinator-receipt",
            {
                "projectExecutionKey": current["projectExecutionKey"],
                "journalVersion": next_version,
                "commandDigest": command["commandDigest"],
                "fencingToken": command["fencingToken"],
            },
        ),
        "receiptType": "WRITE_OBSERVATION",
        "projectExecutionKey": current["projectExecutionKey"],
        "previousJournalVersion": previous_version,
        "nextJournalVersion": next_version,
        "commandDigest": command["commandDigest"],
        "fencingToken": command["fencingToken"],
        "previousState": lease["state"],
        "nextState": lease["state"],
        "authoritySnapshotFingerprint": lease["authoritySnapshotFingerprint"],
        "journalDigest": "sha256:" + "0" * 64,
        "recordedAt": command["processQuiescence"]["observedAt"],
        "evidence": {
            "command": copy.deepcopy(command),
            "observedWriteSet": observed_write_set,
            "revokedLeaseIds": revoked_ids,
            "affectedLeaseDecisions": decisions,
            "recoveryState": "PROJECT_WRITESET_RECOVERY",
        },
    }
    current["receipts"].append(receipt)
    receipt["journalDigest"] = _journal_digest(
        current, len(current["receipts"]) - 1
    )
    persisted = store.replace_journal(previous_version, current, receipt)
    if persisted["receipts"][-1] != receipt:
        raise ControlledCoordinationError(
            "COORDINATOR_POST_WRITE_MISMATCH",
            "persisted quarantine receipt could not be reproduced",
        )
    return _observation_result(receipt)


def observe_lane_writes(
    repository_root: Path,
    source_root: Path,
    command: dict[str, object],
) -> dict[str, object]:
    repository = Path(repository_root).resolve()
    source = Path(source_root).resolve()
    identity = resolve_project_execution_identity(repository, source)
    normalized = normalize_write_observation_command(repository, copy.deepcopy(command))
    if normalized["projectExecutionKey"] != identity["projectExecutionKey"]:
        raise ControlledCoordinationError(
            "PROJECT_EXECUTION_KEY_MISMATCH",
            "observation belongs to another project execution key",
        )
    with CoordinatorStateStore.open(identity) as store:
        with store.exclusive_project_lock():
            journal = store.read_journal()
            if journal is None:
                raise ControlledCoordinationError(
                    "COORDINATOR_LEASE_NOT_FOUND", "observation lease is not durable"
                )
            lease = next(
                (
                    item
                    for item in journal["leases"]
                    if item["leaseId"] == normalized["leaseId"]
                ),
                None,
            )
            if lease is None:
                raise ControlledCoordinationError(
                    "COORDINATOR_LEASE_NOT_FOUND", "observation lease is not durable"
                )
            if lease["originalSourceRoot"] != str(source):
                raise ControlledCoordinationError(
                    "LIVE_AUTHORITY_BINDING_MISMATCH",
                    "observation source does not own the durable lease",
                )
            if lease["fencingToken"] != normalized["fencingToken"]:
                raise ControlledCoordinationError(
                    "STALE_FENCING_TOKEN", "observation fencing token is not current"
                )
            from .controlled_write_guard import _complete_persistent_breach_inventory

            _, observed_paths, remaining_ephemeral = (
                _complete_persistent_breach_inventory(lease)
            )
            if remaining_ephemeral:
                raise ControlledCoordinationError(
                    "EPHEMERAL_PATH_NOT_REMOVED",
                    "declared ephemeral paths must be absent before quarantine",
                )
            if observed_paths != normalized["observedPaths"]:
                raise ControlledCoordinationError(
                    "OBSERVED_WRITESET_MISMATCH",
                    "caller observation does not match the complete live breach set",
                )
            return quarantine_observed_writes_locked(
                store, journal, normalized, observed_paths
            )


def record_project_recovery(
    repository_root: Path,
    source_root: Path,
    command: dict[str, object],
) -> dict[str, object]:
    repository = Path(repository_root).resolve()
    source = Path(source_root).resolve()
    identity = resolve_project_execution_identity(repository, source)
    normalized = normalize_recovery_command(repository, copy.deepcopy(command))
    if normalized["projectExecutionKey"] != identity["projectExecutionKey"]:
        raise ControlledCoordinationError(
            "PROJECT_EXECUTION_KEY_MISMATCH",
            "recovery belongs to another project execution key",
        )
    with CoordinatorStateStore.open(identity) as store:
        with store.exclusive_project_lock():
            observed = store.read_journal()
            if observed is None:
                raise ControlledCoordinationError(
                    "COORDINATOR_STATE_LOST",
                    "recovery requires the complete durable coordinator journal",
                )
            current = copy.deepcopy(observed)
            exact_replay = next(
                (
                    receipt
                    for receipt in current["receipts"]
                    if receipt["receiptType"] == "RECOVERY"
                    and receipt["commandDigest"] == normalized["commandDigest"]
                    and canonical_json_bytes(receipt["evidence"]["command"])
                    == canonical_json_bytes(normalized)
                ),
                None,
            )
            conflicting_recovery = next(
                (
                    receipt
                    for receipt in current["receipts"]
                    if receipt["receiptType"] == "RECOVERY"
                    and receipt["evidence"]["command"]["recoveryId"]
                    == normalized["recoveryId"]
                ),
                None,
            )
            evidence = current.get("recoveryEvidence")
            if not isinstance(evidence, dict):
                if exact_replay is not None:
                    return _recovery_result(exact_replay)
                raise ControlledCoordinationError(
                    "PROJECT_RECOVERY_NOT_PENDING",
                    "project has no durable recovery evidence",
                )
            revoked_ids = evidence["revokedLeaseIds"]
            lease_by_id = {lease["leaseId"]: lease for lease in current["leases"]}
            revoked_leases = [lease_by_id.get(lease_id) for lease_id in revoked_ids]
            if any(lease is None for lease in revoked_leases):
                raise ControlledCoordinationError(
                    "COORDINATOR_STATE_CORRUPT",
                    "recovery evidence names a missing durable lease",
                )
            typed_leases = [lease for lease in revoked_leases if lease is not None]
            if not typed_leases:
                raise ControlledCoordinationError(
                    "COORDINATOR_STATE_CORRUPT",
                    "project recovery cannot close an empty revoked lease set",
                )
            acquire = _acquire_command_for(current, typed_leases[0])
            live_snapshot = _rebuild_transition_snapshot(
                repository, source, identity, acquire
            )
            authority = _current_authority_record(
                live_snapshot,
                reference=normalized["recoveryAuthorityReference"],
                digest=normalized["recoveryAuthorityDigest"],
                authority_id="recovery-controller",
                code="RECOVERY_AUTHORITY_NOT_CURRENT",
            )
            if normalized["recoveryAuthorityId"] != "recovery-controller":
                raise ControlledCoordinationError(
                    "RECOVERY_AUTHORITY_NOT_CURRENT",
                    "recovery command is not issued by recovery-controller",
                )
            public_key = _read_current_authority_bytes(source, authority)
            _verify_sshsig_signature(
                public_key,
                normalized["signature"],
                _recovery_signature_payload(normalized),
                identity="recovery-controller",
                namespace=_RECOVERY_SIGNATURE_NAMESPACE,
                invalid_code="RECOVERY_SIGNATURE_INVALID",
            )
            expected_snapshot_fingerprints = {
                lease["authoritySnapshotFingerprint"] for lease in typed_leases
            }
            if expected_snapshot_fingerprints != {
                live_snapshot["snapshotFingerprint"]
            }:
                raise ControlledCoordinationError(
                    "RECOVERY_AUTHORITY_SNAPSHOT_CHANGED",
                    "recovery cannot clear leases against a changed Authority Snapshot",
                )
            if exact_replay is not None:
                return _recovery_result(exact_replay)
            if conflicting_recovery is not None:
                raise ControlledCoordinationError(
                    "RECOVERY_IDEMPOTENCY_CONFLICT",
                    "recovery identity is already bound to another payload",
                )
            if current["recoveryState"] != "PROJECT_WRITESET_RECOVERY":
                raise ControlledCoordinationError(
                    "PROJECT_RECOVERY_NOT_PENDING",
                    "project has no pending WriteSet recovery",
                )
            if normalized["expectedJournalVersion"] != current["journalVersion"]:
                raise ControlledCoordinationError(
                    "RECOVERY_JOURNAL_VERSION_MISMATCH",
                    "recovery expectedJournalVersion is not current",
                )
            if normalized["observedWriteSet"] != evidence["observedWriteSet"]:
                raise ControlledCoordinationError(
                    "RECOVERY_WRITESET_MISMATCH",
                    "recovery must bind the complete pending observed WriteSet",
                )
            if (
                normalized["affectedLeaseDecisions"]
                != evidence["affectedLeaseDecisions"]
            ):
                raise ControlledCoordinationError(
                    "RECOVERY_DECISION_SET_MISMATCH",
                    "recovery must bind the complete pending lease decisions",
                )
            proof_by_id = {
                proof["leaseId"]: proof
                for proof in normalized["processQuiescenceProofs"]
            }
            if set(proof_by_id) != set(revoked_ids):
                raise ControlledCoordinationError(
                    "RECOVERY_LEASE_SET_MISMATCH",
                    "recovery proofs must name the complete revoked lease set",
                )
            for lease in typed_leases:
                proof = proof_by_id[lease["leaseId"]]
                if proof["fencingToken"] != lease["fencingToken"]:
                    raise ControlledCoordinationError(
                        "RECOVERY_FENCING_PROOF_MISMATCH",
                        "recovery proof does not bind the historical lease token",
                    )
                _validate_lane_physical_identity(lease)

            decisions = {
                item["leaseId"]: item
                for item in normalized["affectedLeaseDecisions"]
            }
            for lease in typed_leases:
                decision = decisions[lease["leaseId"]]
                lease["state"] = decision["decision"]
                lease["released"] = True
                lease["recoveryStatus"] = "CLEAR"
                lease["lastTransitionAt"] = proof_by_id[lease["leaseId"]][
                    "observedAt"
                ]
            previous_version = current["journalVersion"]
            next_version = previous_version + 1
            current["journalVersion"] = next_version
            current["recoveryState"] = "CLEAR"
            current["recoveryEvidence"] = {
                "observedWriteSet": copy.deepcopy(evidence["observedWriteSet"]),
                "revokedLeaseIds": copy.deepcopy(revoked_ids),
                "affectedLeaseDecisions": copy.deepcopy(
                    evidence["affectedLeaseDecisions"]
                ),
                "quarantineCommand": copy.deepcopy(evidence["quarantineCommand"]),
                "recoveryCommand": copy.deepcopy(normalized),
            }
            receipt_token = max(
                proof["fencingToken"]
                for proof in normalized["processQuiescenceProofs"]
            )
            recorded_at = max(
                proof["observedAt"]
                for proof in normalized["processQuiescenceProofs"]
            )
            receipt = {
                "schemaVersion": "controlled-coordinator-receipt/v1",
                "receiptId": _stable_id(
                    "coordinator-receipt",
                    {
                        "projectExecutionKey": current["projectExecutionKey"],
                        "journalVersion": next_version,
                        "commandDigest": normalized["commandDigest"],
                        "fencingToken": receipt_token,
                    },
                ),
                "receiptType": "RECOVERY",
                "projectExecutionKey": current["projectExecutionKey"],
                "previousJournalVersion": previous_version,
                "nextJournalVersion": next_version,
                "commandDigest": normalized["commandDigest"],
                "fencingToken": receipt_token,
                "previousState": None,
                "nextState": None,
                "authoritySnapshotFingerprint": live_snapshot[
                    "snapshotFingerprint"
                ],
                "journalDigest": "sha256:" + "0" * 64,
                "recordedAt": recorded_at,
                "evidence": {
                    "command": copy.deepcopy(normalized),
                    "observedWriteSet": copy.deepcopy(
                        evidence["observedWriteSet"]
                    ),
                    "revokedLeaseIds": copy.deepcopy(revoked_ids),
                    "affectedLeaseDecisions": copy.deepcopy(
                        evidence["affectedLeaseDecisions"]
                    ),
                    "recoveryState": "CLEAR",
                },
            }
            current["receipts"].append(receipt)
            receipt["journalDigest"] = _journal_digest(
                current, len(current["receipts"]) - 1
            )
            persisted = store.replace_journal(previous_version, current, receipt)
            if persisted["receipts"][-1] != receipt:
                raise ControlledCoordinationError(
                    "COORDINATOR_POST_WRITE_MISMATCH",
                    "persisted recovery receipt could not be reproduced",
                )
            return _recovery_result(receipt)
