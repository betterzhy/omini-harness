from __future__ import annotations

import copy
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

from .anchored_fs import AnchoredPathError, AnchoredRoot
from .controlled_conflicts import (
    _conflict_reasons,
    _dependency_closure,
    _owner_closure,
)
from .controlled_coordinator_inputs import (
    ControlledCoordinationError,
    normalize_acquire_command,
)
from .coordinator_state import CoordinatorStateStore
from .hashing import canonical_json_bytes, sha256_bytes
from .registration import ProjectRegistrationError, load_project_registration


_TERMINAL_STATES = frozenset({"CLOSED", "CANCELLED"})


def _sha256(value: Any) -> str:
    return "sha256:" + sha256_bytes(canonical_json_bytes(value))


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}:" + sha256_bytes(canonical_json_bytes(value))[:24]


def _source_stat(path: Path) -> os.stat_result:
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ControlledCoordinationError(
            "PROJECT_EXECUTION_IDENTITY_INVALID",
            "registered source root cannot be opened no-follow",
        ) from exc
    if not stat.S_ISDIR(current.st_mode):
        raise ControlledCoordinationError(
            "PROJECT_EXECUTION_IDENTITY_INVALID",
            "registered source root must be a no-follow directory",
        )
    return current


def _same_physical_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino, stat.S_IFMT(left.st_mode)) == (
        right.st_dev,
        right.st_ino,
        stat.S_IFMT(right.st_mode),
    )


def resolve_project_execution_identity(
    repository_root: Path,
    source_root: Path,
) -> dict[str, str | int]:
    """Resolve one registered physical repository to its project lock identity."""
    source_input = Path(source_root)
    before = _source_stat(source_input)
    try:
        loaded = load_project_registration(repository_root, source_input)
    except ProjectRegistrationError as exc:
        raise ControlledCoordinationError(
            "PROJECT_EXECUTION_IDENTITY_INVALID", str(exc)
        ) from exc
    source = Path(loaded["sourceRoot"])
    after = _source_stat(source)
    if not _same_physical_identity(before, after):
        raise ControlledCoordinationError(
            "PROJECT_EXECUTION_IDENTITY_CHANGED",
            "registered source root identity changed during resolution",
        )
    registration = copy.deepcopy(loaded["registration"])
    physical = {
        "device": after.st_dev,
        "inode": after.st_ino,
        "type": stat.S_IFMT(after.st_mode),
    }
    project_execution_key = "project-execution:" + sha256_bytes(
        canonical_json_bytes(
            {
                "schemaVersion": "project-execution-identity-material/v1",
                "registration": registration,
                "sourceRootIdentity": physical,
            }
        )
    )
    return {
        "schemaVersion": "project-execution-identity/v1",
        "projectExecutionKey": project_execution_key,
        "harnessId": registration["harnessId"],
        "integrationId": registration["integrationId"],
        "integrationPath": registration["integrationPath"],
        "sourceAccess": registration["sourceAccess"],
        "runtime": registration["runtime"],
        "capabilityLockFingerprint": registration["capabilityLockFingerprint"],
        "sourceRoot": str(source),
        "sourceDevice": after.st_dev,
        "sourceInode": after.st_ino,
        "sourceType": "DIRECTORY",
    }


def _git_identity(source_root: Path) -> tuple[Path, str]:
    try:
        top_level = Path(
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
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ControlledCoordinationError(
            "SOURCE_HEAD_UNAVAILABLE", "registered source must be a readable Git repository"
        ) from exc
    return top_level, head


def _validate_lane_root(source_root: Path, command: dict[str, Any]) -> None:
    lane_root = Path(command["laneRoot"])
    approved_root = source_root.parent / f"{source_root.name}-lanes"
    try:
        relative = lane_root.relative_to(approved_root)
    except ValueError as exc:
        raise ControlledCoordinationError(
            "LANE_ROOT_OUTSIDE_ISOLATION",
            "lane root is outside the project-approved isolation root",
        ) from exc
    if not relative.parts:
        raise ControlledCoordinationError(
            "LANE_ROOT_OUTSIDE_ISOLATION",
            "the isolation root itself cannot be used as a lane root",
        )


def _validate_live_authority_files(
    source_root: Path, snapshot: dict[str, Any]
) -> None:
    records = snapshot["authorities"]
    by_id = {item["id"]: item for item in records}
    by_path = {item["path"]: item for item in records}
    if len(by_id) != len(records) or len(by_path) != len(records):
        raise ControlledCoordinationError(
            "AUTHORITY_RECORD_DUPLICATE", "authority identities and paths must be unique"
        )
    for fact_id, fact in snapshot["facts"].items():
        record = by_id.get(fact["owner"])
        if record is None or record["path"] != fact["sourcePath"]:
            raise ControlledCoordinationError(
                "LIVE_AUTHORITY_BINDING_MISMATCH",
                f"authority fact is not bound to its declared live record: {fact_id}",
            )

    try:
        with AnchoredRoot(source_root) as filesystem:
            for record in records:
                before = filesystem.lstat(record["path"])
                if before is None or not stat.S_ISREG(before.st_mode):
                    raise ControlledCoordinationError(
                        "AUTHORITY_FILE_UNSAFE",
                        f"authority path is missing or not a regular file: {record['path']}",
                    )
                data = filesystem.read_bytes(record["path"])
                after = filesystem.lstat(record["path"])
                if after is None or not _same_physical_identity(before, after):
                    raise ControlledCoordinationError(
                        "AUTHORITY_FILE_CHANGED_DURING_READ",
                        f"authority path identity changed during validation: {record['path']}",
                    )
                if sha256_bytes(data) != record["sha256"]:
                    raise ControlledCoordinationError(
                        "AUTHORITY_FILE_CHANGED",
                        f"authority content changed after snapshot: {record['path']}",
                    )
    except AnchoredPathError as exc:
        raise ControlledCoordinationError(
            "AUTHORITY_FILE_UNSAFE", "authority path cannot be opened no-follow"
        ) from exc


def _validate_live_bindings(
    repository_root: Path,
    source_root: Path,
    identity: dict[str, Any],
    command: dict[str, Any],
) -> None:
    current_identity = resolve_project_execution_identity(repository_root, source_root)
    if current_identity != identity:
        raise ControlledCoordinationError(
            "PROJECT_EXECUTION_IDENTITY_CHANGED",
            "project registration or physical source identity changed under lock",
        )
    try:
        loaded = load_project_registration(repository_root, source_root)
    except ProjectRegistrationError as exc:
        raise ControlledCoordinationError("PROJECT_REGISTRATION_CHANGED", str(exc)) from exc
    registration = loaded["registration"]
    integration = loaded["integration"]["config"]
    snapshot = command["authoritySnapshot"]
    if (
        command["originalSourceRoot"] != str(source_root)
        or registration["integrationId"] != snapshot["integrationId"]
        or integration["id"] != snapshot["integrationId"]
        or integration["projectId"] != command["projectId"]
        or snapshot["projectId"] != command["projectId"]
        or registration["sourceAccess"] != "READ_ONLY"
    ):
        raise ControlledCoordinationError(
            "LIVE_AUTHORITY_BINDING_MISMATCH",
            "registration, integration, source, and command identities do not agree",
        )
    top_level, head = _git_identity(source_root)
    if top_level != source_root or head != command["expectedLaneBase"]:
        raise ControlledCoordinationError(
            "SOURCE_HEAD_CHANGED", "registered source HEAD differs from the planned lane base"
        )
    _validate_lane_root(source_root, command)
    _validate_live_authority_files(source_root, snapshot)


def _is_nonterminal(lease: dict[str, Any]) -> bool:
    return not (
        lease["state"] in _TERMINAL_STATES and lease["released"] is True
    )


def _footprints_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
    descriptors = [left, right]
    return bool(
        _conflict_reasons(
            left,
            right,
            _dependency_closure(descriptors),
            _owner_closure(descriptors),
        )
    )


def _idempotency_tuple(
    project_execution_key: str, command: dict[str, Any]
) -> tuple[str, Any, Any, Any]:
    return (
        project_execution_key,
        command.get("batchPlanId"),
        command.get("sliceId"),
        command.get("attemptId"),
    )


def _lease_tuple(lease: dict[str, Any]) -> tuple[str, Any, Any, Any]:
    return (
        lease["projectExecutionKey"],
        lease["batchPlanId"],
        lease["sliceId"],
        lease["attemptId"],
    )


def _acquire_receipt_for(
    journal: dict[str, Any], lease: dict[str, Any]
) -> dict[str, Any] | None:
    for receipt in journal["receipts"]:
        if receipt["receiptType"] != "ACQUIRE":
            continue
        command = receipt["evidence"]["command"]
        if (
            command["batchPlanId"],
            command["sliceId"],
            command["attemptId"],
        ) == (lease["batchPlanId"], lease["sliceId"], lease["attemptId"]):
            return receipt
    return None


def _empty_journal(project_execution_key: str) -> dict[str, Any]:
    return {
        "schemaVersion": "controlled-coordinator-journal/v1",
        "projectExecutionKey": project_execution_key,
        "journalVersion": 0,
        "nextFencingToken": 1,
        "recoveryState": "CLEAR",
        "recoveryEvidence": None,
        "leases": [],
        "receipts": [],
        "integrationTransactions": [],
    }


def _journal_digest(journal: dict[str, Any], receipt_index: int) -> str:
    payload = copy.deepcopy(journal)
    payload["receipts"][receipt_index]["journalDigest"] = "sha256:" + "0" * 64
    return _sha256(payload)


def acquire_lane_lease(
    repository_root: Path,
    source_root: Path,
    command: dict[str, object],
) -> dict[str, object]:
    """Atomically admit one project lane and return its durable fenced lease."""
    repository = Path(repository_root).resolve()
    source = Path(source_root).resolve()
    identity = resolve_project_execution_identity(repository, source_root)
    project_execution_key = identity["projectExecutionKey"]
    with CoordinatorStateStore.open(identity) as store:
        with store.exclusive_project_lock():
            journal = store.read_journal()
            current = (
                _empty_journal(project_execution_key)
                if journal is None
                else copy.deepcopy(journal)
            )
            if current["recoveryState"] != "CLEAR":
                raise ControlledCoordinationError(
                    "COORDINATOR_RECOVERY_REQUIRED",
                    "project coordinator recovery must close before admission",
                )

            raw = copy.deepcopy(command)
            requested_key = _idempotency_tuple(project_execution_key, raw)
            existing = next(
                (lease for lease in current["leases"] if _lease_tuple(lease) == requested_key),
                None,
            )
            if existing is not None:
                if not _is_nonterminal(existing):
                    raise ControlledCoordinationError(
                        "TERMINAL_ACQUISITION_REPLAY",
                        "a terminal attempt requires a new project-authorized attempt identity",
                    )
                receipt = _acquire_receipt_for(current, existing)
                if (
                    receipt is None
                    or receipt["commandDigest"] != raw.get("commandDigest")
                ):
                    raise ControlledCoordinationError(
                        "ACQUISITION_IDEMPOTENCY_CONFLICT",
                        "the acquisition idempotency key is bound to another payload",
                    )
                normalized_replay = normalize_acquire_command(repository, raw)
                _validate_live_bindings(
                    repository, source, identity, normalized_replay
                )
                if canonical_json_bytes(receipt["evidence"]["command"]) != canonical_json_bytes(
                    normalized_replay
                ):
                    raise ControlledCoordinationError(
                        "ACQUISITION_IDEMPOTENCY_CONFLICT",
                        "the acquisition idempotency key payload changed",
                    )
                return copy.deepcopy(existing)

            normalized = normalize_acquire_command(repository, raw)
            _validate_live_bindings(repository, source, identity, normalized)
            active = [lease for lease in current["leases"] if _is_nonterminal(lease)]
            if any(
                lease["authorizationEnvelopeDigest"]
                != normalized["authorizationEnvelopeDigest"]
                for lease in active
            ):
                raise ControlledCoordinationError(
                    "AUTHORIZATION_ENVELOPE_CHANGED",
                    "nonterminal lanes were admitted by a different envelope",
                )
            if any(
                lease["conflictPolicyVersion"] != normalized["conflictPolicyVersion"]
                for lease in active
            ):
                raise ControlledCoordinationError(
                    "CONFLICT_POLICY_CHANGED",
                    "nonterminal lanes were admitted by a different conflict policy",
                )
            if any(
                lease["expectedLaneBase"] != normalized["expectedLaneBase"]
                for lease in active
            ):
                raise ControlledCoordinationError(
                    "SOURCE_HEAD_CHANGED",
                    "nonterminal lanes are fenced to another source HEAD",
                )
            if any(lease["laneRoot"] == normalized["laneRoot"] for lease in active):
                raise ControlledCoordinationError(
                    "LANE_ROOT_CONFLICT", "lane roots are exclusive across nonterminal leases"
                )
            if any(
                _footprints_conflict(lease["fullFootprint"], normalized["fullFootprint"])
                for lease in active
            ):
                raise ControlledCoordinationError(
                    "ACTIVE_FOOTPRINT_CONFLICT",
                    "proposed footprint conflicts with a nonterminal project lease",
                )
            lane_cap = min(normalized["authorizationEnvelope"]["maxParallelLanes"], 3)
            if len(active) >= lane_cap:
                raise ControlledCoordinationError(
                    "PROJECT_CAPACITY_LIMIT", "project-wide lane capacity is exhausted"
                )

            previous_version = current["journalVersion"]
            token = current["nextFencingToken"]
            lease = {
                "schemaVersion": "controlled-execution-lease/v1",
                "projectExecutionKey": project_execution_key,
                "leaseId": _stable_id("lease", requested_key),
                "batchPlanId": normalized["batchPlanId"],
                "sliceId": normalized["sliceId"],
                "attemptId": normalized["attemptId"],
                "authoritySnapshotFingerprint": normalized[
                    "authoritySnapshotFingerprint"
                ],
                "authorizationEnvelopeDigest": normalized[
                    "authorizationEnvelopeDigest"
                ],
                "conflictPolicyVersion": normalized["conflictPolicyVersion"],
                "descriptorDigest": normalized["sliceDescriptor"]["descriptorDigest"],
                "fullFootprint": copy.deepcopy(normalized["fullFootprint"]),
                "originalSourceRoot": normalized["originalSourceRoot"],
                "laneRoot": normalized["laneRoot"],
                "expectedLaneBase": normalized["expectedLaneBase"],
                "fencingToken": token,
                "state": "ADMITTED",
                "candidateIdentity": None,
                "acquiredAt": normalized["asOf"],
                "lastTransitionAt": normalized["asOf"],
                "released": False,
                "recoveryStatus": "CLEAR",
            }
            next_version = previous_version + 1
            current["journalVersion"] = next_version
            current["nextFencingToken"] = token + 1
            current["leases"].append(lease)
            receipt = {
                "schemaVersion": "controlled-coordinator-receipt/v1",
                "receiptId": _stable_id(
                    "coordinator-receipt",
                    {
                        "projectExecutionKey": project_execution_key,
                        "journalVersion": next_version,
                        "commandDigest": normalized["commandDigest"],
                        "fencingToken": token,
                    },
                ),
                "receiptType": "ACQUIRE",
                "projectExecutionKey": project_execution_key,
                "previousJournalVersion": previous_version,
                "nextJournalVersion": next_version,
                "commandDigest": normalized["commandDigest"],
                "fencingToken": token,
                "previousState": None,
                "nextState": "ADMITTED",
                "authoritySnapshotFingerprint": normalized[
                    "authoritySnapshotFingerprint"
                ],
                "journalDigest": "sha256:" + "0" * 64,
                "recordedAt": normalized["asOf"],
                "evidence": {"command": normalized},
            }
            current["receipts"].append(receipt)
            receipt["journalDigest"] = _journal_digest(
                current, len(current["receipts"]) - 1
            )
            persisted = store.replace_journal(previous_version, current, receipt)
            persisted_lease = next(
                item for item in persisted["leases"] if item["leaseId"] == lease["leaseId"]
            )
            if persisted_lease != lease or persisted["receipts"][-1] != receipt:
                raise ControlledCoordinationError(
                    "COORDINATOR_POST_WRITE_MISMATCH",
                    "persisted acquisition did not reproduce lease and receipt",
                )
            return copy.deepcopy(persisted_lease)
