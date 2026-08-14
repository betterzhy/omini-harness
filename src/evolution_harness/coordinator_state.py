from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import stat
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Iterator

from .controlled_coordinator_inputs import ControlledCoordinationError
from .hashing import canonical_json_bytes, sha256_bytes
from .schema import SchemaStore, SchemaValidationError


_JOURNAL_SCHEMA = "core/schemas/controlled-coordinator-journal.schema.json"
_RECEIPT_SCHEMA = "core/schemas/controlled-coordinator-receipt.schema.json"
_ROOT_IDENTITY_NAME = ".root-identity.json"
_PROJECT_KEY = re.compile(r"^project-execution:[0-9a-f]{64}$")
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_MAX_STATE_BYTES = 64 * 1024 * 1024
_RECOVERY_SIGNATURE_NAMESPACE = "agent-evolution-controlled-recovery-v1"
_PLANNING_FOOTPRINT_FIELDS = (
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


@dataclass(frozen=True)
class _JournalSnapshot:
    journal: dict[str, Any]
    canonical_bytes: bytes
    inode: os.stat_result


def _current_uid() -> int:
    return os.getuid()


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino, stat.S_IFMT(left.st_mode)) == (
        right.st_dev,
        right.st_ino,
        stat.S_IFMT(right.st_mode),
    )


def _read_all(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        size += len(chunk)
        if size > _MAX_STATE_BYTES:
            raise ValueError("coordinator state file exceeds the size limit")
        chunks.append(chunk)


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("short coordinator state write")
        remaining = remaining[written:]


def _json_object(raw: bytes) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates)
    if not isinstance(value, dict):
        raise ValueError("coordinator state must be a JSON object")
    return value


def _state_corrupt(message: str) -> None:
    raise ControlledCoordinationError("COORDINATOR_STATE_CORRUPT", message)


def _expected_receipt_id(receipt: dict[str, Any]) -> str:
    payload = {
        "projectExecutionKey": receipt["projectExecutionKey"],
        "journalVersion": receipt["nextJournalVersion"],
        "commandDigest": receipt["commandDigest"],
        "fencingToken": receipt["fencingToken"],
    }
    return "coordinator-receipt:" + sha256_bytes(
        canonical_json_bytes(payload)
    )[:24]


def _recovery_signature_payload(command: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in command.items()
        if key not in {"signature", "commandDigest"}
    }


def _validate_persisted_recovery_authority(
    command: dict[str, Any],
    revoked_ids: list[str],
    acquire_commands: dict[str, dict[str, Any]],
) -> None:
    anchors: set[tuple[str, str]] = set()
    for lease_id in revoked_ids:
        acquire = acquire_commands.get(lease_id)
        if acquire is None:
            _state_corrupt("recovery authority has no immutable Acquire anchor")
        matches = [
            authority
            for authority in acquire["authoritySnapshot"]["authorities"]
            if authority["id"] == "recovery-controller"
        ]
        if len(matches) != 1:
            _state_corrupt(
                "Acquire Authority Snapshot has no unique recovery-controller"
            )
        anchors.add((matches[0]["path"], "sha256:" + matches[0]["sha256"]))
    commanded_anchor = (
        command["recoveryAuthorityReference"],
        command["recoveryAuthorityDigest"],
    )
    if (
        command["recoveryAuthorityId"] != "recovery-controller"
        or anchors != {commanded_anchor}
    ):
        _state_corrupt("persisted recovery authority diverges from Acquire evidence")
    try:
        public_key = command["recoveryAuthorityPublicKey"].encode("ascii")
    except UnicodeEncodeError:
        _state_corrupt("persisted recovery public key is not canonical ASCII")
    if "sha256:" + sha256_bytes(public_key) != command["recoveryAuthorityDigest"]:
        _state_corrupt("persisted recovery public key does not match its anchor")

    from .controlled_coordinator import _verify_sshsig_signature

    try:
        _verify_sshsig_signature(
            public_key,
            command["signature"],
            _recovery_signature_payload(command),
            identity="recovery-controller",
            namespace=_RECOVERY_SIGNATURE_NAMESPACE,
            invalid_code="RECOVERY_SIGNATURE_INVALID",
        )
    except ControlledCoordinationError as exc:
        if exc.code == "SSH_KEYGEN_VERIFIER_INVALID":
            raise
        _state_corrupt("persisted recovery SSHSIG is not authority-valid")


def _acquire_planning_footprints(command: dict[str, Any]) -> list[dict[str, Any]]:
    footprints = []
    for descriptor in command["planningRequest"]["slices"]:
        footprint = {"sliceId": descriptor["sliceId"]}
        for field in _PLANNING_FOOTPRINT_FIELDS:
            footprint[field] = copy.deepcopy(descriptor[field])
        footprint["conflictFootprintId"] = (
            "footprint:"
            + sha256_bytes(
                canonical_json_bytes(
                    {
                        "projectId": command["projectId"],
                        "conflictPolicyVersion": command["conflictPolicyVersion"],
                        **footprint,
                    }
                )
            )[:24]
        )
        footprints.append(footprint)
    return sorted(footprints, key=lambda item: item["sliceId"])


def _path_is_within(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _paths_overlap(left: str, right: str) -> bool:
    return _path_is_within(left, right) or _path_is_within(right, left)


def _expected_recovery_decisions(
    leases: list[dict[str, Any]],
    acquire_commands: dict[str, dict[str, Any]],
    revoked_ids: list[str],
    observed_write_set: list[str],
) -> list[dict[str, str]]:
    decisions = []
    lease_by_id = {lease["leaseId"]: lease for lease in leases}
    for lease_id in revoked_ids:
        lease = lease_by_id.get(lease_id)
        command = acquire_commands.get(lease_id)
        if lease is None or command is None:
            _state_corrupt("recovery evidence names a lease without Acquire evidence")
        authority_paths = sorted(
            {
                *command["sliceDescriptor"]["authorityReferences"],
                *(
                    authority["path"]
                    for authority in command["authoritySnapshot"]["authorities"]
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
            {"leaseId": lease_id, "decision": decision, "reason": reason}
        )
    return sorted(decisions, key=lambda item: item["leaseId"])


def _validate_recovery_integrity(
    journal: dict[str, Any],
    acquire_commands: dict[str, dict[str, Any]],
    observation_receipts: list[dict[str, Any]],
    recovery_receipts: list[dict[str, Any]],
) -> None:
    evidence = journal["recoveryEvidence"]
    mutation_receipts = [
        receipt
        for receipt in journal["receipts"]
        if receipt["receiptType"] in {"WRITE_OBSERVATION", "RECOVERY"}
    ]
    if len(mutation_receipts) != len(observation_receipts) + len(recovery_receipts):
        _state_corrupt("recovery receipt indexes do not cover the mutation chain")

    lease_by_id = {lease["leaseId"]: lease for lease in journal["leases"]}
    historical_leases: dict[str, dict[str, Any]] = {}
    recovery_pending = False
    pending_revoked_ids: list[str] = []
    for receipt in journal["receipts"]:
        receipt_type = receipt["receiptType"]
        command = receipt["evidence"]["command"]
        if receipt_type == "ACQUIRE":
            if recovery_pending:
                _state_corrupt(
                    "coordinator mutation occurred while recovery was pending"
                )
            matches = [
                lease
                for lease in journal["leases"]
                if (
                    lease["batchPlanId"],
                    lease["sliceId"],
                    lease["attemptId"],
                )
                == (
                    command["batchPlanId"],
                    command["sliceId"],
                    command["attemptId"],
                )
            ]
            if len(matches) != 1:
                _state_corrupt("Acquire receipt has no unique historical lease")
            historical_leases[matches[0]["leaseId"]] = {
                "state": "ADMITTED",
                "released": False,
            }
        elif receipt_type == "TRANSITION":
            if recovery_pending:
                _state_corrupt(
                    "coordinator mutation occurred while recovery was pending"
                )
            historical = historical_leases.get(command["leaseId"])
            if historical is None:
                _state_corrupt("transition has no historical acquired lease")
            historical["state"] = command["nextState"]
            historical["released"] = command["nextState"] == "CLOSED"
        elif receipt_type == "WRITE_OBSERVATION":
            recoverable_ids = sorted(
                lease_id
                for lease_id, historical in historical_leases.items()
                if not historical["released"] and historical["state"] != "CLOSED"
            )
            if receipt["evidence"]["revokedLeaseIds"] != recoverable_ids:
                _state_corrupt(
                    "WRITE_OBSERVATION omits a historical recoverable lease"
                )
            recovery_pending = True
            pending_revoked_ids = recoverable_ids
        elif receipt_type == "RECOVERY":
            if not recovery_pending:
                _state_corrupt("RECOVERY receipt has no pending observation cycle")
            decisions = {
                item["leaseId"]: item
                for item in receipt["evidence"]["affectedLeaseDecisions"]
            }
            if set(decisions) != set(pending_revoked_ids):
                _state_corrupt("RECOVERY omits one pending revoked lease")
            for lease_id in pending_revoked_ids:
                historical_leases[lease_id]["state"] = decisions[lease_id][
                    "decision"
                ]
                historical_leases[lease_id]["released"] = True
            recovery_pending = False
            pending_revoked_ids = []

    cycles: list[tuple[list[dict[str, Any]], dict[str, Any] | None]] = []
    pending_observations: list[dict[str, Any]] = []
    for receipt in mutation_receipts:
        if receipt["receiptType"] == "WRITE_OBSERVATION":
            pending_observations.append(receipt)
            continue
        if not pending_observations:
            _state_corrupt("RECOVERY receipt has no preceding WRITE_OBSERVATION")
        cycles.append((pending_observations, receipt))
        pending_observations = []
    if pending_observations:
        cycles.append((pending_observations, None))

    if not cycles:
        if evidence is not None or journal["recoveryState"] != "CLEAR":
            _state_corrupt("recovery evidence requires a WRITE_OBSERVATION receipt")
        return
    if evidence is None:
        _state_corrupt("recovery receipts require complete journal evidence")

    latest_cycle_evidence: dict[str, Any] | None = None
    for cycle_index, (observations, recovery) in enumerate(cycles):
        latest_observation = observations[-1]["evidence"]
        revoked_ids = latest_observation["revokedLeaseIds"]
        revoked_set = set(revoked_ids)
        if not revoked_ids or revoked_ids != sorted(revoked_set):
            _state_corrupt("recovery revoked lease identities must be a canonical set")
        if revoked_set - set(lease_by_id):
            _state_corrupt("recovery evidence names a missing durable lease")

        cumulative_paths: list[str] = []
        expected_decisions: list[dict[str, str]] = []
        for receipt in observations:
            command = receipt["evidence"]["command"]
            observed_lease = lease_by_id.get(command["leaseId"])
            if (
                observed_lease is None
                or command["leaseId"] not in revoked_set
                or command["fencingToken"] != receipt["fencingToken"]
                or command["fencingToken"] != observed_lease["fencingToken"]
                or receipt["authoritySnapshotFingerprint"]
                != observed_lease["authoritySnapshotFingerprint"]
                or receipt["recordedAt"]
                != command["processQuiescence"]["observedAt"]
                or receipt["previousState"] != receipt["nextState"]
            ):
                _state_corrupt("WRITE_OBSERVATION is not bound to one revoked lease")
            if command["observedPaths"] != sorted(set(command["observedPaths"])):
                _state_corrupt("WRITE_OBSERVATION paths are not canonical")
            cumulative_paths = sorted({*cumulative_paths, *command["observedPaths"]})
            expected_decisions = _expected_recovery_decisions(
                journal["leases"], acquire_commands, revoked_ids, cumulative_paths
            )
            receipt_evidence = receipt["evidence"]
            if (
                receipt_evidence["observedWriteSet"] != cumulative_paths
                or receipt_evidence["revokedLeaseIds"] != revoked_ids
                or receipt_evidence["affectedLeaseDecisions"] != expected_decisions
                or receipt_evidence["recoveryState"]
                != "PROJECT_WRITESET_RECOVERY"
            ):
                _state_corrupt("WRITE_OBSERVATION does not preserve its recovery cycle")

        latest_cycle_evidence = {
            "observedWriteSet": cumulative_paths,
            "revokedLeaseIds": revoked_ids,
            "affectedLeaseDecisions": expected_decisions,
            "quarantineCommand": latest_observation["command"],
            "recoveryCommand": None,
        }
        is_latest = cycle_index == len(cycles) - 1
        if recovery is None:
            if not is_latest or journal["recoveryState"] != "PROJECT_WRITESET_RECOVERY":
                _state_corrupt("only the latest recovery cycle may remain pending")
            if any(
                lease_by_id[lease_id]["released"]
                or lease_by_id[lease_id]["recoveryStatus"]
                != "PROJECT_WRITESET_RECOVERY"
                for lease_id in revoked_ids
            ):
                _state_corrupt(
                    "pending recovery leases must remain retained and quarantined"
                )
            continue

        command = recovery["evidence"]["command"]
        proofs = command["processQuiescenceProofs"]
        proof_by_id = {proof["leaseId"]: proof for proof in proofs}
        decisions = {item["leaseId"]: item for item in expected_decisions}
        bound_snapshot_fingerprints = {
            lease_by_id[lease_id]["authoritySnapshotFingerprint"]
            for lease_id in revoked_ids
        }
        if (
            len(proof_by_id) != len(proofs)
            or command["expectedJournalVersion"]
            != recovery["previousJournalVersion"]
            or command["observedWriteSet"] != cumulative_paths
            or command["affectedLeaseDecisions"] != expected_decisions
            or set(proof_by_id) != revoked_set
            or recovery["fencingToken"]
            != max(proof["fencingToken"] for proof in proofs)
            or bound_snapshot_fingerprints
            != {recovery["authoritySnapshotFingerprint"]}
            or recovery["recordedAt"]
            != max(proof["observedAt"] for proof in proofs)
            or recovery["previousState"] is not None
            or recovery["nextState"] is not None
            or recovery["evidence"]["observedWriteSet"] != cumulative_paths
            or recovery["evidence"]["revokedLeaseIds"] != revoked_ids
            or recovery["evidence"]["affectedLeaseDecisions"]
            != expected_decisions
            or recovery["evidence"]["recoveryState"] != "CLEAR"
        ):
            _state_corrupt(
                "RECOVERY receipt does not preserve complete recovery evidence"
            )
        _validate_persisted_recovery_authority(
            command, revoked_ids, acquire_commands
        )
        for lease_id in revoked_ids:
            lease = lease_by_id[lease_id]
            proof = proof_by_id[lease_id]
            if (
                proof["fencingToken"] != lease["fencingToken"]
                or lease["state"] != decisions[lease_id]["decision"]
                or lease["released"] is not True
                or lease["recoveryStatus"] != "CLEAR"
            ):
                _state_corrupt(
                    "released lease does not preserve its recovery decision"
                )
        latest_cycle_evidence["recoveryCommand"] = command
        if is_latest and journal["recoveryState"] != "CLEAR":
            _state_corrupt("completed WriteSet recovery must leave state CLEAR")

    if evidence != latest_cycle_evidence:
        _state_corrupt("journal recovery evidence diverges from the latest cycle")


def _validate_journal_integrity(
    journal: dict[str, Any], *, persisted: bool = False
) -> None:
    receipts = journal["receipts"]
    leases = journal["leases"]
    if persisted and journal["journalVersion"] == 0:
        _state_corrupt(
            "an initialized store cannot persist the in-memory empty journal sentinel"
        )
    if any(
        lease["projectExecutionKey"] != journal["projectExecutionKey"]
        for lease in leases
    ):
        _state_corrupt("lease belongs to another project execution key")
    lease_ids = [lease["leaseId"] for lease in leases]
    idempotency_keys = [
        (lease["batchPlanId"], lease["sliceId"], lease["attemptId"])
        for lease in leases
    ]
    if len(lease_ids) != len(set(lease_ids)) or len(idempotency_keys) != len(
        set(idempotency_keys)
    ):
        _state_corrupt("lease identities and acquisition keys must be unique")
    active = [
        lease
        for lease in leases
        if not (
            lease["state"] in {"CLOSED", "CANCELLED"}
            and lease["released"] is True
        )
    ]
    lane_paths = [lease["laneRoot"] for lease in active]
    lane_identities = [
        (
            lease["lanePhysicalIdentity"]["device"],
            lease["lanePhysicalIdentity"]["inode"],
            lease["lanePhysicalIdentity"]["type"],
        )
        for lease in active
    ]
    if len(lane_paths) != len(set(lane_paths)) or len(lane_identities) != len(
        set(lane_identities)
    ):
        _state_corrupt("active lease lanes must be logically and physically unique")
    if journal["journalVersion"] != len(receipts):
        _state_corrupt("journal version does not match the complete receipt chain")
    acquire_receipt_counts = {lease["leaseId"]: 0 for lease in leases}
    acquire_commands: dict[str, dict[str, Any]] = {}
    observation_receipts: list[dict[str, Any]] = []
    recovery_receipts: list[dict[str, Any]] = []
    for index, receipt in enumerate(receipts, start=1):
        if (
            receipt["projectExecutionKey"] != journal["projectExecutionKey"]
            or receipt["previousJournalVersion"] != index - 1
            or receipt["nextJournalVersion"] != index
        ):
            _state_corrupt("receipt versions or project identity do not form one chain")
        if (
            receipt["receiptType"] == "RECOVERY"
            and receipt["receiptId"] != _expected_receipt_id(receipt)
        ):
            _state_corrupt("receipt identity is not deterministic for its command")
        command = receipt["evidence"]["command"]
        if receipt["commandDigest"] != command["commandDigest"]:
            _state_corrupt("receipt command digest is not associated with its evidence")
        expected_command_digest = "sha256:" + sha256_bytes(
            canonical_json_bytes(
                {
                    key: value
                    for key, value in command.items()
                    if key != "commandDigest"
                }
            )
        )
        if command["commandDigest"] != expected_command_digest:
            _state_corrupt("receipt command evidence digest is not canonical")
        if receipt["receiptType"] == "ACQUIRE":
            associated = [
                lease
                for lease in leases
                if (
                    lease["batchPlanId"],
                    lease["sliceId"],
                    lease["attemptId"],
                )
                == (
                    command["batchPlanId"],
                    command["sliceId"],
                    command["attemptId"],
                )
            ]
        elif receipt["receiptType"] == "TRANSITION":
            associated = [
                lease
                for lease in leases
                if lease["leaseId"] == command["leaseId"]
                and lease["attemptId"] == command["attemptId"]
            ]
        else:
            associated = []
        if receipt["receiptType"] in {"ACQUIRE", "TRANSITION"} and (
            len(associated) != 1
            or associated[0]["fencingToken"] != receipt["fencingToken"]
            or command.get("fencingToken", receipt["fencingToken"])
            != receipt["fencingToken"]
        ):
            _state_corrupt("receipt is not associated with exactly one fenced lease")
        if receipt["receiptType"] == "ACQUIRE":
            lease = associated[0]
            acquire_receipt_counts[lease["leaseId"]] += 1
            acquire_commands[lease["leaseId"]] = command
            expected_lease_bindings = {
                "batchPlanId": command["batchPlanId"],
                "sliceId": command["sliceId"],
                "attemptId": command["attemptId"],
                "authoritySnapshotFingerprint": command[
                    "authoritySnapshotFingerprint"
                ],
                "authorizationEnvelopeDigest": command[
                    "authorizationEnvelopeDigest"
                ],
                "conflictPolicyVersion": command["conflictPolicyVersion"],
                "descriptorDigest": command["sliceDescriptor"]["descriptorDigest"],
                "fullFootprint": command["fullFootprint"],
                "originalSourceRoot": command["originalSourceRoot"],
                "laneRoot": command["laneRoot"],
                "expectedLaneBase": command["expectedLaneBase"],
            }
            if any(
                canonical_json_bytes(lease[field])
                != canonical_json_bytes(expected_value)
                for field, expected_value in expected_lease_bindings.items()
            ) or lease["planningFootprints"] != _acquire_planning_footprints(command):
                _state_corrupt(
                    "acquired lease does not preserve its authority-bound command graph"
                )
        elif receipt["receiptType"] == "TRANSITION" and (
            receipt["previousState"] != command["expectedState"]
            or receipt["nextState"] != command["nextState"]
            or receipt["authoritySnapshotFingerprint"]
            != command["authoritySnapshotFingerprint"]
        ):
            _state_corrupt("transition receipt does not preserve its command binding")
        elif receipt["receiptType"] == "WRITE_OBSERVATION":
            observation_receipts.append(receipt)
        elif receipt["receiptType"] == "RECOVERY":
            recovery_receipts.append(receipt)

    if any(count != 1 for count in acquire_receipt_counts.values()):
        _state_corrupt("every persisted lease must have exactly one ACQUIRE receipt")

    _validate_recovery_integrity(
        journal, acquire_commands, observation_receipts, recovery_receipts
    )

    tokens = [lease["fencingToken"] for lease in leases]
    if len(tokens) != len(set(tokens)):
        _state_corrupt("persisted lease fencing tokens must be unique")
    durable_tokens = tokens + [receipt["fencingToken"] for receipt in receipts]
    if durable_tokens and journal["nextFencingToken"] <= max(durable_tokens):
        _state_corrupt("next fencing token is not above all durable tokens")

    if receipts:
        payload = copy.deepcopy(journal)
        observed = payload["receipts"][-1]["journalDigest"]
        payload["receipts"][-1]["journalDigest"] = "sha256:" + "0" * 64
        expected = "sha256:" + sha256_bytes(canonical_json_bytes(payload))
        if observed != expected:
            _state_corrupt("latest receipt does not digest the complete journal")


def _validate_directory(current: os.stat_result, *, uid: int) -> None:
    if (
        not stat.S_ISDIR(current.st_mode)
        or current.st_uid != uid
        or stat.S_IMODE(current.st_mode) != 0o700
    ):
        raise ControlledCoordinationError(
            "UNSAFE_COORDINATOR_ROOT",
            "coordinator root must be an owner-only 0700 directory",
        )


def _validate_regular(
    current: os.stat_result, *, uid: int, code: str = "UNSAFE_COORDINATOR_STATE_FILE"
) -> None:
    if (
        not stat.S_ISREG(current.st_mode)
        or current.st_uid != uid
        or stat.S_IMODE(current.st_mode) != 0o600
        or current.st_nlink != 1
    ):
        raise ControlledCoordinationError(
            code,
            "coordinator state files must be owner-only 0600 regular files with one link",
        )


def _configured_root() -> Path:
    configured = os.environ.get("AGENT_EVOLUTION_COORDINATOR_ROOT")
    if configured is None:
        return Path.home() / ".codex/state/agent-evolution-harness/coordinator/v1"
    if not configured or "\x00" in configured:
        raise ControlledCoordinationError(
            "UNSAFE_COORDINATOR_ROOT", "coordinator root must be a nonempty absolute path"
        )
    path = Path(configured)
    if not path.is_absolute() or any(part in {".", ".."} for part in PurePath(configured).parts):
        raise ControlledCoordinationError(
            "UNSAFE_COORDINATOR_ROOT", "coordinator root must be a canonical absolute path"
        )
    return path


def _open_or_create_root(path: Path) -> int:
    current = os.open("/", _DIRECTORY_FLAGS)
    try:
        parts = path.parts[1:]
        if not parts:
            raise ControlledCoordinationError(
                "UNSAFE_COORDINATOR_ROOT", "filesystem root cannot be coordinator state"
            )
        for index, part in enumerate(parts):
            following = -1
            try:
                try:
                    following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
                except FileNotFoundError:
                    try:
                        os.mkdir(part, 0o700, dir_fd=current)
                    except FileExistsError:
                        pass
                    except OSError as exc:
                        raise ControlledCoordinationError(
                            "UNSAFE_COORDINATOR_ROOT",
                            f"cannot safely create coordinator root component {part}",
                        ) from exc
                    try:
                        following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
                    except OSError as exc:
                        raise ControlledCoordinationError(
                            "UNSAFE_COORDINATOR_ROOT",
                            f"racing coordinator root component is unsafe: {part}",
                        ) from exc
                    _validate_directory(os.fstat(following), uid=_current_uid())
                    try:
                        os.fsync(current)
                    except OSError as exc:
                        raise ControlledCoordinationError(
                            "UNSAFE_COORDINATOR_ROOT",
                            f"cannot durably create coordinator root component {part}",
                        ) from exc
                except OSError as exc:
                    raise ControlledCoordinationError(
                        "UNSAFE_COORDINATOR_ROOT",
                        f"coordinator root component is unsafe: {part}",
                    ) from exc
                if index == len(parts) - 1:
                    _validate_directory(os.fstat(following), uid=_current_uid())
            except BaseException:
                if following >= 0:
                    os.close(following)
                raise
            previous = current
            current = following
            following = -1
            os.close(previous)
        return current
    except BaseException:
        os.close(current)
        raise


def _open_existing_root(path: Path) -> int | None:
    current = os.open("/", _DIRECTORY_FLAGS)
    try:
        parts = path.parts[1:]
        if not parts:
            raise ControlledCoordinationError(
                "UNSAFE_COORDINATOR_ROOT", "filesystem root cannot be coordinator state"
            )
        for index, part in enumerate(parts):
            try:
                following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
            except FileNotFoundError:
                os.close(current)
                return None
            except OSError as exc:
                raise ControlledCoordinationError(
                    "UNSAFE_COORDINATOR_ROOT",
                    f"coordinator root component is unsafe: {part}",
                ) from exc
            try:
                if index == len(parts) - 1:
                    _validate_directory(os.fstat(following), uid=_current_uid())
            except BaseException:
                os.close(following)
                raise
            previous = current
            current = following
            os.close(previous)
        return current
    except BaseException:
        os.close(current)
        raise


class CoordinatorStateStore:
    def __init__(self, root: Path, root_descriptor: int, identity: dict[str, Any]):
        self.root = root
        self._root_descriptor = root_descriptor
        self.identity = copy.deepcopy(identity)
        self.project_execution_key = identity["projectExecutionKey"]
        self._owner_uid = _current_uid()
        self._lock_descriptor: int | None = None
        self._schema_store = SchemaStore(Path(__file__).resolve().parents[2])
        project_name = sha256_bytes(self.project_execution_key.encode("utf-8"))
        self._lock_name = f"{project_name}.lock"
        self._lock_identity_name = f"{project_name}.lock-identity"
        self._journal_name = f"{project_name}.journal.json"
        self._initialized_name = f"{project_name}.initialized"

    @classmethod
    def open(cls, identity: dict[str, Any]) -> "CoordinatorStateStore":
        if (
            not isinstance(identity, dict)
            or not isinstance(identity.get("projectExecutionKey"), str)
            or not _PROJECT_KEY.fullmatch(identity["projectExecutionKey"])
        ):
            raise ControlledCoordinationError(
                "PROJECT_EXECUTION_IDENTITY_INVALID",
                "identity must contain a canonical projectExecutionKey",
            )
        root = _configured_root()
        descriptor = _open_or_create_root(root)
        store = cls(root, descriptor, identity)
        try:
            store._open_or_validate_root_identity()
        except BaseException:
            store.close()
            raise
        return store

    @classmethod
    def open_read_only(
        cls, identity: dict[str, Any]
    ) -> "CoordinatorStateStore | None":
        if (
            not isinstance(identity, dict)
            or not isinstance(identity.get("projectExecutionKey"), str)
            or not _PROJECT_KEY.fullmatch(identity["projectExecutionKey"])
        ):
            raise ControlledCoordinationError(
                "PROJECT_EXECUTION_IDENTITY_INVALID",
                "identity must contain a canonical projectExecutionKey",
            )
        root = _configured_root()
        descriptor = _open_existing_root(root)
        if descriptor is None:
            return None
        store = cls(root, descriptor, identity)
        try:
            store._verify_root_identity()
        except BaseException:
            store.close()
            raise
        return store

    def __enter__(self) -> "CoordinatorStateStore":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        if self._lock_descriptor is not None:
            try:
                fcntl.flock(self._lock_descriptor, fcntl.LOCK_UN)
            finally:
                os.close(self._lock_descriptor)
                self._lock_descriptor = None
        if self._root_descriptor >= 0:
            os.close(self._root_descriptor)
            self._root_descriptor = -1

    def _ensure_open(self) -> None:
        if self._root_descriptor < 0:
            raise ControlledCoordinationError(
                "COORDINATOR_STORE_CLOSED", "coordinator state store is closed"
            )

    def _root_identity(self) -> dict[str, Any]:
        current = os.fstat(self._root_descriptor)
        return {
            "schemaVersion": "coordinator-root-identity/v1",
            "rootPath": str(self.root),
            "rootDevice": current.st_dev,
            "rootInode": current.st_ino,
            "ownerUid": self._owner_uid,
        }

    def _open_or_validate_root_identity(self) -> None:
        expected = self._root_identity()
        try:
            observed = self._read_state_json(
                _ROOT_IDENTITY_NAME,
                missing_code="COORDINATOR_ROOT_IDENTITY_MISSING",
                unsafe_code="UNSAFE_COORDINATOR_ROOT",
                expected_uid=self._owner_uid,
            )
        except ControlledCoordinationError as exc:
            if exc.code != "COORDINATOR_ROOT_IDENTITY_MISSING":
                raise
            payload = canonical_json_bytes(expected) + b"\n"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC
            descriptor = -1
            try:
                descriptor = os.open(
                    _ROOT_IDENTITY_NAME,
                    flags,
                    0o600,
                    dir_fd=self._root_descriptor,
                )
                _validate_regular(os.fstat(descriptor), uid=self._owner_uid, code="UNSAFE_COORDINATOR_ROOT")
                _write_all(descriptor, payload)
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = -1
                os.fsync(self._root_descriptor)
            except FileExistsError:
                if descriptor >= 0:
                    os.close(descriptor)
                observed = self._read_state_json(
                    _ROOT_IDENTITY_NAME,
                    missing_code="COORDINATOR_ROOT_IDENTITY_MISSING",
                    unsafe_code="UNSAFE_COORDINATOR_ROOT",
                    expected_uid=self._owner_uid,
                )
            except OSError as write_error:
                if descriptor >= 0:
                    os.close(descriptor)
                raise ControlledCoordinationError(
                    "UNSAFE_COORDINATOR_ROOT", "cannot durably initialize coordinator root identity"
                ) from write_error
            else:
                observed = expected
        if observed != expected:
            raise ControlledCoordinationError(
                "COORDINATOR_ROOT_IDENTITY_MISMATCH",
                "coordinator root identity does not match its opened directory",
            )

    def _verify_root_identity(self) -> None:
        self._ensure_open()
        _validate_directory(os.fstat(self._root_descriptor), uid=self._owner_uid)
        observed = self._read_state_json(
            _ROOT_IDENTITY_NAME,
            missing_code="COORDINATOR_ROOT_IDENTITY_MISSING",
            unsafe_code="UNSAFE_COORDINATOR_ROOT",
            expected_uid=self._owner_uid,
        )
        if observed != self._root_identity():
            raise ControlledCoordinationError(
                "COORDINATOR_ROOT_IDENTITY_MISMATCH",
                "coordinator root identity changed while the store was open",
            )

    def _path_stat(self, name: str) -> os.stat_result:
        return os.stat(name, dir_fd=self._root_descriptor, follow_symlinks=False)

    def _optional_regular_stat(
        self, name: str, *, code: str = "UNSAFE_COORDINATOR_STATE_FILE"
    ) -> os.stat_result | None:
        try:
            current = self._path_stat(name)
        except FileNotFoundError:
            return None
        _validate_regular(current, uid=self._owner_uid, code=code)
        return current

    def _assert_journal_inode(self, expected: os.stat_result | None) -> None:
        try:
            observed = self._path_stat(self._journal_name)
        except FileNotFoundError as exc:
            if expected is None:
                return
            raise ControlledCoordinationError(
                "COORDINATOR_STATE_INODE_CHANGED",
                "coordinator journal disappeared before atomic replacement",
            ) from exc
        _validate_regular(observed, uid=_current_uid())
        if expected is None or not _same_inode(expected, observed):
            raise ControlledCoordinationError(
                "COORDINATOR_STATE_INODE_CHANGED",
                "coordinator journal inode changed before atomic replacement",
            )

    def _read_state_bytes_with_inode(
        self,
        name: str,
        *,
        missing_code: str,
        unsafe_code: str,
        expected_uid: int,
    ) -> tuple[bytes, os.stat_result]:
        try:
            before = self._path_stat(name)
        except FileNotFoundError as exc:
            raise ControlledCoordinationError(missing_code, f"coordinator state file is missing: {name}") from exc
        _validate_regular(before, uid=expected_uid, code=unsafe_code)
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | _NOFOLLOW | _CLOEXEC,
                dir_fd=self._root_descriptor,
            )
        except OSError as exc:
            raise ControlledCoordinationError(unsafe_code, f"cannot safely open coordinator state file: {name}") from exc
        try:
            opened = os.fstat(descriptor)
            _validate_regular(opened, uid=expected_uid, code=unsafe_code)
            if not _same_inode(before, opened):
                raise ControlledCoordinationError(
                    "COORDINATOR_STATE_INODE_CHANGED", f"coordinator state inode changed before open: {name}"
                )
            try:
                payload = _read_all(descriptor)
            except (OSError, ValueError) as exc:
                raise ControlledCoordinationError(
                    "COORDINATOR_JOURNAL_INVALID", f"cannot read coordinator state file: {name}"
                ) from exc
            try:
                after = self._path_stat(name)
            except FileNotFoundError as exc:
                raise ControlledCoordinationError(
                    "COORDINATOR_STATE_INODE_CHANGED",
                    f"coordinator state inode disappeared during read: {name}",
                ) from exc
            if not _same_inode(opened, after):
                raise ControlledCoordinationError(
                    "COORDINATOR_STATE_INODE_CHANGED", f"coordinator state inode changed during read: {name}"
                )
            return payload, opened
        finally:
            os.close(descriptor)

    def _read_state_bytes(
        self,
        name: str,
        *,
        missing_code: str,
        unsafe_code: str,
        expected_uid: int,
    ) -> bytes:
        payload, _ = self._read_state_bytes_with_inode(
            name,
            missing_code=missing_code,
            unsafe_code=unsafe_code,
            expected_uid=expected_uid,
        )
        return payload

    def _read_state_json(
        self,
        name: str,
        *,
        missing_code: str,
        unsafe_code: str,
        expected_uid: int,
    ) -> dict[str, Any]:
        raw = self._read_state_bytes(
            name,
            missing_code=missing_code,
            unsafe_code=unsafe_code,
            expected_uid=expected_uid,
        )
        try:
            return _json_object(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            code = (
                "COORDINATOR_ROOT_IDENTITY_MISMATCH"
                if name == _ROOT_IDENTITY_NAME
                else "COORDINATOR_JOURNAL_INVALID"
            )
            raise ControlledCoordinationError(code, f"invalid coordinator JSON file: {name}") from exc

    def _read_marker(self) -> dict[str, Any] | None:
        try:
            marker = self._read_state_json(
                self._initialized_name,
                missing_code="COORDINATOR_MARKER_MISSING",
                unsafe_code="UNSAFE_COORDINATOR_STATE_FILE",
                expected_uid=_current_uid(),
            )
        except ControlledCoordinationError as exc:
            if exc.code == "COORDINATOR_MARKER_MISSING":
                return None
            raise
        expected = {
            "schemaVersion": "coordinator-project-initialized/v1",
            "projectExecutionKey": self.project_execution_key,
        }
        if marker != expected:
            raise ControlledCoordinationError(
                "COORDINATOR_JOURNAL_INVALID", "project initialization marker is invalid"
            )
        return marker

    def _lock_identity(self, current: os.stat_result) -> dict[str, Any]:
        return {
            "schemaVersion": "coordinator-project-lock-identity/v1",
            "projectExecutionKey": self.project_execution_key,
            "lockDevice": current.st_dev,
            "lockInode": current.st_ino,
        }

    def _read_lock_identity(self) -> dict[str, Any] | None:
        try:
            return self._read_state_json(
                self._lock_identity_name,
                missing_code="COORDINATOR_LOCK_IDENTITY_MISSING",
                unsafe_code="COORDINATOR_LOCK_IDENTITY_MISMATCH",
                expected_uid=_current_uid(),
            )
        except ControlledCoordinationError as exc:
            if exc.code == "COORDINATOR_LOCK_IDENTITY_MISSING":
                return None
            if exc.code != "COORDINATOR_LOCK_IDENTITY_MISMATCH":
                raise ControlledCoordinationError(
                    "COORDINATOR_LOCK_IDENTITY_MISMATCH",
                    "project lock identity is invalid",
                ) from exc
            raise

    def _bind_or_validate_lock_identity(
        self,
        descriptor: int,
        opened: os.stat_result,
        observed: dict[str, Any] | None,
    ) -> None:
        expected = self._lock_identity(opened)
        named = self._path_stat(self._lock_name)
        if not _same_inode(opened, named):
            raise ControlledCoordinationError(
                "COORDINATOR_LOCK_IDENTITY_MISMATCH",
                "project lock path changed before identity binding",
            )
        if observed is None:
            identity_descriptor = -1
            try:
                os.fsync(descriptor)
                os.fsync(self._root_descriptor)
                identity_descriptor = os.open(
                    self._lock_identity_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC,
                    0o600,
                    dir_fd=self._root_descriptor,
                )
                _validate_regular(os.fstat(identity_descriptor), uid=_current_uid())
                _write_all(identity_descriptor, canonical_json_bytes(expected) + b"\n")
                os.fsync(identity_descriptor)
                os.close(identity_descriptor)
                identity_descriptor = -1
                os.fsync(self._root_descriptor)
                observed = expected
            except FileExistsError:
                if identity_descriptor >= 0:
                    os.close(identity_descriptor)
                observed = self._read_lock_identity()
            except OSError as exc:
                if identity_descriptor >= 0:
                    os.close(identity_descriptor)
                raise ControlledCoordinationError(
                    "COORDINATOR_LOCK_IDENTITY_MISMATCH",
                    "cannot durably bind project lock identity",
                ) from exc
        if observed != expected:
            raise ControlledCoordinationError(
                "COORDINATOR_LOCK_IDENTITY_MISMATCH",
                "project lock inode does not match its persistent identity",
            )
        named = self._path_stat(self._lock_name)
        if not _same_inode(opened, named):
            raise ControlledCoordinationError(
                "COORDINATOR_LOCK_IDENTITY_MISMATCH",
                "project lock path changed after identity binding",
            )

    @contextmanager
    def exclusive_project_lock(self) -> Iterator[None]:
        self._verify_root_identity()
        if self._lock_descriptor is not None:
            raise ControlledCoordinationError(
                "COORDINATOR_LOCK_BUSY", "project lock is not reentrant"
            )
        initialized = self._read_marker()
        lock_identity = self._read_lock_identity() if initialized is not None else None
        if initialized is not None and lock_identity is None:
            raise ControlledCoordinationError(
                "COORDINATOR_LOCK_IDENTITY_MISMATCH",
                "initialized project is missing its persistent lock identity",
            )
        flags = os.O_RDWR | _NOFOLLOW | _CLOEXEC
        if initialized is None:
            flags |= os.O_CREAT
        descriptor = -1
        try:
            descriptor = os.open(
                self._lock_name,
                flags,
                0o600,
                dir_fd=self._root_descriptor,
            )
            opened = os.fstat(descriptor)
            _validate_regular(opened, uid=_current_uid())
            named = self._path_stat(self._lock_name)
            if not _same_inode(opened, named):
                raise ControlledCoordinationError(
                    "COORDINATOR_LOCK_IDENTITY_MISMATCH",
                    "project lock inode changed before flock",
                )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ControlledCoordinationError(
                    "COORDINATOR_LOCK_BUSY", "another process holds the project coordinator lock"
                ) from exc
            if initialized is None:
                lock_identity = self._read_lock_identity()
            self._bind_or_validate_lock_identity(descriptor, opened, lock_identity)
        except ControlledCoordinationError:
            if descriptor >= 0:
                os.close(descriptor)
            raise
        except FileNotFoundError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            raise ControlledCoordinationError(
                "COORDINATOR_LOCK_IDENTITY_MISMATCH",
                "persistently bound project lock is missing",
            ) from exc
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            raise ControlledCoordinationError(
                "UNSAFE_COORDINATOR_STATE_FILE", "cannot safely open project coordinator lock"
            ) from exc

        self._lock_descriptor = descriptor
        try:
            self._verify_root_identity()
            self._bind_or_validate_lock_identity(
                descriptor, opened, self._read_lock_identity()
            )
            yield
            named = self._path_stat(self._lock_name)
            if not _same_inode(opened, named):
                raise ControlledCoordinationError(
                    "COORDINATOR_STATE_INODE_CHANGED", "project lock inode changed while held"
                )
        finally:
            if self._lock_descriptor is not None:
                try:
                    fcntl.flock(self._lock_descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(self._lock_descriptor)
                    self._lock_descriptor = None

    @contextmanager
    def exclusive_existing_project_lock(self) -> Iterator[bool]:
        """Lock initialized state without creating root or project artifacts."""
        self._verify_root_identity()
        if self._lock_descriptor is not None:
            raise ControlledCoordinationError(
                "COORDINATOR_LOCK_BUSY", "project lock is not reentrant"
            )
        initialized = self._read_marker()
        lock_identity = self._read_lock_identity()
        lock_stat = self._optional_regular_stat(
            self._lock_name, code="COORDINATOR_LOCK_IDENTITY_MISMATCH"
        )
        journal_stat = self._optional_regular_stat(self._journal_name)
        if initialized is None:
            if (
                lock_identity is not None
                and lock_stat is not None
                and journal_stat is None
            ):
                descriptor = -1
                try:
                    descriptor = os.open(
                        self._lock_name,
                        os.O_RDWR | _NOFOLLOW | _CLOEXEC,
                        dir_fd=self._root_descriptor,
                    )
                    opened = os.fstat(descriptor)
                    _validate_regular(
                        opened,
                        uid=self._owner_uid,
                        code="COORDINATOR_LOCK_IDENTITY_MISMATCH",
                    )
                    if not _same_inode(lock_stat, opened):
                        raise ControlledCoordinationError(
                            "COORDINATOR_LOCK_IDENTITY_MISMATCH",
                            "project lock inode changed before read-only flock",
                        )
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError as exc:
                        raise ControlledCoordinationError(
                            "COORDINATOR_LOCK_BUSY",
                            "another process holds the project coordinator lock",
                        ) from exc
                    self._bind_or_validate_lock_identity(
                        descriptor, opened, lock_identity
                    )
                except ControlledCoordinationError:
                    raise
                except OSError as exc:
                    raise ControlledCoordinationError(
                        "UNSAFE_COORDINATOR_STATE_FILE",
                        "cannot safely inspect existing project coordinator lock",
                    ) from exc
                finally:
                    if descriptor >= 0:
                        try:
                            fcntl.flock(descriptor, fcntl.LOCK_UN)
                        finally:
                            os.close(descriptor)
                raise ControlledCoordinationError(
                    "COORDINATOR_STATE_INCONSISTENT",
                    "uninitialized coordinator has persistent project state",
                )
            if (
                lock_identity is not None
                or lock_stat is not None
                or journal_stat is not None
            ):
                raise ControlledCoordinationError(
                    "COORDINATOR_STATE_INCONSISTENT",
                    "uninitialized coordinator has persistent project state",
                )
            yield False
            self._verify_root_identity()
            if (
                self._read_marker() is not None
                or self._read_lock_identity() is not None
                or self._optional_regular_stat(
                    self._lock_name, code="COORDINATOR_LOCK_IDENTITY_MISMATCH"
                )
                is not None
                or self._optional_regular_stat(self._journal_name) is not None
            ):
                raise ControlledCoordinationError(
                    "COORDINATOR_STATE_INODE_CHANGED",
                    "coordinator state appeared during read-only inspection",
                )
            return
        if lock_identity is None or lock_stat is None:
            raise ControlledCoordinationError(
                "COORDINATOR_LOCK_IDENTITY_MISMATCH",
                "initialized project is missing its persistent lock identity",
            )

        descriptor = -1
        try:
            descriptor = os.open(
                self._lock_name,
                os.O_RDWR | _NOFOLLOW | _CLOEXEC,
                dir_fd=self._root_descriptor,
            )
            opened = os.fstat(descriptor)
            _validate_regular(
                opened, uid=self._owner_uid, code="COORDINATOR_LOCK_IDENTITY_MISMATCH"
            )
            if not _same_inode(lock_stat, opened):
                raise ControlledCoordinationError(
                    "COORDINATOR_LOCK_IDENTITY_MISMATCH",
                    "project lock inode changed before read-only flock",
                )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ControlledCoordinationError(
                    "COORDINATOR_LOCK_BUSY",
                    "another process holds the project coordinator lock",
                ) from exc
            self._bind_or_validate_lock_identity(descriptor, opened, lock_identity)
        except ControlledCoordinationError:
            if descriptor >= 0:
                os.close(descriptor)
            raise
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            raise ControlledCoordinationError(
                "UNSAFE_COORDINATOR_STATE_FILE",
                "cannot safely open existing project coordinator lock",
            ) from exc

        self._lock_descriptor = descriptor
        try:
            self._verify_root_identity()
            self._bind_or_validate_lock_identity(
                descriptor, opened, self._read_lock_identity()
            )
            yield True
            named = self._path_stat(self._lock_name)
            if not _same_inode(opened, named):
                raise ControlledCoordinationError(
                    "COORDINATOR_STATE_INODE_CHANGED",
                    "project lock inode changed while held",
                )
        finally:
            if self._lock_descriptor is not None:
                try:
                    fcntl.flock(self._lock_descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(self._lock_descriptor)
                    self._lock_descriptor = None

    def _read_journal_snapshot(self) -> _JournalSnapshot | None:
        self._verify_root_identity()
        initialized = self._read_marker()
        try:
            raw, inode = self._read_state_bytes_with_inode(
                self._journal_name,
                missing_code="COORDINATOR_JOURNAL_ABSENT",
                unsafe_code="UNSAFE_COORDINATOR_STATE_FILE",
                expected_uid=_current_uid(),
            )
        except ControlledCoordinationError as exc:
            if exc.code == "COORDINATOR_JOURNAL_ABSENT":
                if initialized is not None:
                    raise ControlledCoordinationError(
                        "COORDINATOR_JOURNAL_MISSING",
                        "previously initialized coordinator journal is missing",
                    ) from exc
                return None
            raise
        try:
            journal = _json_object(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ControlledCoordinationError(
                "COORDINATOR_JOURNAL_INVALID", "invalid coordinator journal JSON"
            ) from exc
        try:
            self._schema_store.validate(_JOURNAL_SCHEMA, journal)
        except (SchemaValidationError, FileNotFoundError) as exc:
            raise ControlledCoordinationError(
                "COORDINATOR_JOURNAL_INVALID", str(exc)
            ) from exc
        if journal["projectExecutionKey"] != self.project_execution_key:
            raise ControlledCoordinationError(
                "COORDINATOR_JOURNAL_IDENTITY_MISMATCH",
                "journal belongs to a different project execution key",
            )
        _validate_journal_integrity(journal, persisted=True)
        if initialized is None:
            raise ControlledCoordinationError(
                "COORDINATOR_STATE_INCONSISTENT",
                "coordinator journal exists without its initialization marker",
            )
        return _JournalSnapshot(
            journal=journal,
            canonical_bytes=canonical_json_bytes(journal) + b"\n",
            inode=inode,
        )

    def read_journal(self) -> dict[str, Any] | None:
        snapshot = self._read_journal_snapshot()
        return None if snapshot is None else snapshot.journal

    def _validate_replacement(
        self,
        expected_version: int,
        journal: dict[str, Any],
        receipt: dict[str, Any],
    ) -> None:
        try:
            self._schema_store.validate(_RECEIPT_SCHEMA, receipt)
            self._schema_store.validate(_JOURNAL_SCHEMA, journal)
        except (SchemaValidationError, FileNotFoundError) as exc:
            raise ControlledCoordinationError(
                "COORDINATOR_JOURNAL_INVALID", str(exc)
            ) from exc
        if (
            journal["projectExecutionKey"] != self.project_execution_key
            or receipt["projectExecutionKey"] != self.project_execution_key
        ):
            raise ControlledCoordinationError(
                "COORDINATOR_JOURNAL_IDENTITY_MISMATCH",
                "journal or receipt belongs to a different project",
            )
        _validate_journal_integrity(journal, persisted=True)
        if (
            journal["journalVersion"] != expected_version + 1
            or receipt["previousJournalVersion"] != expected_version
            or receipt["nextJournalVersion"] != journal["journalVersion"]
        ):
            raise ControlledCoordinationError(
                "STALE_JOURNAL_VERSION", "journal and receipt versions do not form the requested CAS"
            )
        if not journal["receipts"] or journal["receipts"][-1] != receipt:
            raise ControlledCoordinationError(
                "COORDINATOR_RECEIPT_MISMATCH",
                "the persisted journal must end with the supplied mutation receipt",
            )

    def _write_initialized_marker(self) -> None:
        expected = {
            "schemaVersion": "coordinator-project-initialized/v1",
            "projectExecutionKey": self.project_execution_key,
        }
        existing = self._read_marker()
        if existing is not None:
            return
        descriptor = -1
        try:
            descriptor = os.open(
                self._initialized_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC,
                0o600,
                dir_fd=self._root_descriptor,
            )
            _validate_regular(os.fstat(descriptor), uid=_current_uid())
            _write_all(descriptor, canonical_json_bytes(expected) + b"\n")
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.fsync(self._root_descriptor)
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            raise ControlledCoordinationError(
                "COORDINATOR_DURABILITY_UNCERTAIN",
                "project initialization marker durability is uncertain",
            ) from exc

    def _verify_cas_snapshot(
        self, expected: _JournalSnapshot | None
    ) -> None:
        observed = self._read_journal_snapshot()
        if expected is None:
            if observed is not None:
                raise ControlledCoordinationError(
                    "COORDINATOR_STATE_INODE_CHANGED",
                    "coordinator journal appeared during initial CAS",
                )
            return
        if observed is None or not _same_inode(expected.inode, observed.inode):
            raise ControlledCoordinationError(
                "COORDINATOR_STATE_INODE_CHANGED",
                "coordinator journal inode changed after CAS read",
            )
        if observed.canonical_bytes != expected.canonical_bytes:
            raise ControlledCoordinationError(
                "COORDINATOR_CAS_SNAPSHOT_CHANGED",
                "coordinator journal payload changed after CAS read",
            )

    def replace_journal(
        self,
        expected_version: int,
        journal: dict[str, Any],
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        if self._lock_descriptor is None:
            raise ControlledCoordinationError(
                "COORDINATOR_LOCK_REQUIRED", "journal replacement requires the project lock"
            )
        current_snapshot = self._read_journal_snapshot()
        current = None if current_snapshot is None else current_snapshot.journal
        current_version = 0 if current is None else current["journalVersion"]
        if current_version != expected_version:
            raise ControlledCoordinationError(
                "STALE_JOURNAL_VERSION",
                f"expected journal version {expected_version}, found {current_version}",
            )
        candidate = copy.deepcopy(journal)
        candidate_receipt = copy.deepcopy(receipt)
        current_receipts = [] if current is None else current["receipts"]
        if (
            not isinstance(candidate.get("receipts"), list)
            or candidate["receipts"][:-1] != current_receipts
        ):
            raise ControlledCoordinationError(
                "COORDINATOR_RECEIPT_HISTORY_REWRITE",
                "journal replacement must preserve the complete ordered receipt history",
            )
        self._validate_replacement(expected_version, candidate, candidate_receipt)
        payload = canonical_json_bytes(candidate) + b"\n"
        temporary = f".{self._journal_name}.tmp-{uuid.uuid4().hex}"
        descriptor = -1
        replaced = False
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC,
                0o600,
                dir_fd=self._root_descriptor,
            )
            _validate_regular(os.fstat(descriptor), uid=_current_uid())
            _write_all(descriptor, payload)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            self._verify_root_identity()
            self._verify_cas_snapshot(current_snapshot)
            if current_snapshot is None:
                self._write_initialized_marker()
                self._assert_journal_inode(None)
            os.replace(
                temporary,
                self._journal_name,
                src_dir_fd=self._root_descriptor,
                dst_dir_fd=self._root_descriptor,
            )
            replaced = True
            try:
                os.fsync(self._root_descriptor)
            except OSError as exc:
                raise ControlledCoordinationError(
                    "COORDINATOR_DURABILITY_UNCERTAIN",
                    "journal replacement is visible but directory durability is uncertain",
                ) from exc
        except ControlledCoordinationError:
            raise
        except OSError as exc:
            raise ControlledCoordinationError(
                "COORDINATOR_STATE_WRITE_FAILED",
                "coordinator journal atomic replacement failed",
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if not replaced:
                try:
                    os.unlink(temporary, dir_fd=self._root_descriptor)
                except FileNotFoundError:
                    pass
        persisted_snapshot = self._read_journal_snapshot()
        if (
            persisted_snapshot is None
            or persisted_snapshot.canonical_bytes != payload
        ):
            raise ControlledCoordinationError(
                "COORDINATOR_POST_WRITE_MISMATCH",
                "post-write journal reread did not reproduce the complete candidate",
            )
        return persisted_snapshot.journal
