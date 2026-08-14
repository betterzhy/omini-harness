from __future__ import annotations

import copy
import os
import re
import stat
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .authority import IntegrationAuthorityError, build_authority_snapshot
from .controlled_conflicts import (
    _conflict_reasons,
    _dependency_closure,
    _owner_closure,
    build_conflict_report,
)
from .controlled_coordinator_inputs import (
    ControlledCoordinationError,
    normalize_acquire_command,
    normalize_transition_command,
)
from .coordinator_state import CoordinatorStateStore
from .controlled_write_guard import (
    _close_git_boundary,
    _open_git_boundary,
    _read_git_head,
    _read_git_object,
)
from .hashing import canonical_json_bytes, sha256_bytes
from .registration import ProjectRegistrationError, load_project_registration


_TERMINAL_STATES = frozenset({"CLOSED", "CANCELLED"})
_ALLOWED_LEASE_TRANSITIONS = MappingProxyType(
    {
        "ADMITTED": frozenset({"ACTIVE", "BLOCKED", "NO_GO", "STALE", "CANCELLED"}),
        "ACTIVE": frozenset(
            {"FIXED_CANDIDATE", "BLOCKED", "NO_GO", "STALE", "CANCELLED"}
        ),
        "FIXED_CANDIDATE": frozenset(
            {"REVIEW_GO", "BLOCKED", "NO_GO", "STALE", "CANCELLED"}
        ),
        "REVIEW_GO": frozenset(
            {
                "QUEUED_FOR_INTEGRATION",
                "BLOCKED",
                "NO_GO",
                "STALE",
                "CANCELLED",
            }
        ),
        "QUEUED_FOR_INTEGRATION": frozenset(
            {"INTEGRATING", "BLOCKED", "NO_GO", "STALE", "CANCELLED"}
        ),
        "INTEGRATING": frozenset(
            {"CLOSED", "BLOCKED", "NO_GO", "STALE", "CANCELLED"}
        ),
    }
)
_CANDIDATE_STATES = frozenset(
    {
        "FIXED_CANDIDATE",
        "REVIEW_GO",
        "QUEUED_FOR_INTEGRATION",
        "INTEGRATING",
        "CLOSED",
    }
)
_REVOCATION_STATES = frozenset({"STALE", "CANCELLED"})
_SSH_KEYGEN_PATH = "/usr/bin/ssh-keygen"
_SSH_KEYGEN_SHA256 = (
    "bddae9c4ea46fd903574ec6ff61eda75e133f940fa538f2adca80af474767596"
)
_LIFECYCLE_SIGNATURE_NAMESPACE = "agent-evolution-controlled-lifecycle-v1"
_REVIEW_SIGNATURE_NAMESPACE = "agent-evolution-controlled-review-v1"
_SSHSIG_ARMOR = re.compile(
    rb"\A-----BEGIN SSH SIGNATURE-----\n"
    rb"(?:[A-Za-z0-9+/]+={0,2}\n)+"
    rb"-----END SSH SIGNATURE-----\n\Z"
)


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


def inspect_project_coordinator(
    repository_root: Path,
    source_root: Path,
) -> dict[str, object]:
    """Read one project's durable coordinator safety status under its lock."""
    identity = resolve_project_execution_identity(repository_root, source_root)
    store = CoordinatorStateStore.open_read_only(identity)
    if store is not None:
        with store:
            with store.exclusive_existing_project_lock() as initialized:
                journal = store.read_journal() if initialized else None
                if journal is not None:
                    leases = [
                        {
                            "leaseId": lease["leaseId"],
                            "batchPlanId": lease["batchPlanId"],
                            "sliceId": lease["sliceId"],
                            "attemptId": lease["attemptId"],
                            "fencingToken": lease["fencingToken"],
                            "state": lease["state"],
                            "released": lease["released"],
                            "retained": not lease["released"],
                            "recoveryStatus": lease["recoveryStatus"],
                        }
                        for lease in journal["leases"]
                    ]
                    latest_receipt = journal["receipts"][-1]
                    return {
                        "schemaVersion": "controlled-coordinator-status/v1",
                        "projectExecutionKey": identity["projectExecutionKey"],
                        "initialized": True,
                        "journalVersion": journal["journalVersion"],
                        "nextFencingToken": journal["nextFencingToken"],
                        "recoveryState": journal["recoveryState"],
                        "latestReceiptId": latest_receipt["receiptId"],
                        "journalDigest": latest_receipt["journalDigest"],
                        "retainedLeaseIds": [
                            lease["leaseId"] for lease in leases if lease["retained"]
                        ],
                        "releasedLeaseIds": [
                            lease["leaseId"] for lease in leases if lease["released"]
                        ],
                        "leases": leases,
                    }
    return {
        "schemaVersion": "controlled-coordinator-status/v1",
        "projectExecutionKey": identity["projectExecutionKey"],
        "initialized": False,
        "journalVersion": 0,
        "nextFencingToken": 1,
        "recoveryState": "CLEAR",
        "latestReceiptId": None,
        "journalDigest": None,
        "retainedLeaseIds": [],
        "releasedLeaseIds": [],
        "leases": [],
    }


def _git_identity(source_root: Path) -> tuple[Path, str]:
    source_descriptor = -1
    boundary = None
    try:
        source_descriptor, observed = _open_absolute_directory_no_follow(source_root)
        source_identity = (observed.st_dev, observed.st_ino, stat.S_IFMT(observed.st_mode))
        boundary = _open_git_boundary(
            source_descriptor,
            source_root,
            source_identity,
            error_code="SOURCE_HEAD_UNAVAILABLE",
            error_message="registered source Git identity is not physically sealed",
        )
        top_level = source_root
        head = _read_git_head(boundary)
    except (ControlledCoordinationError, OSError, ValueError) as exc:
        if isinstance(exc, ControlledCoordinationError) and exc.code == "SOURCE_HEAD_UNAVAILABLE":
            raise
        raise ControlledCoordinationError(
            "SOURCE_HEAD_UNAVAILABLE", "registered source must be a readable Git repository"
        ) from exc
    finally:
        _close_git_boundary(boundary)
        if source_descriptor >= 0:
            os.close(source_descriptor)
    return top_level, head


_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _open_absolute_directory_no_follow(path: Path) -> tuple[int, os.stat_result]:
    current = os.open("/", _DIRECTORY_FLAGS)
    try:
        for part in path.parts[1:]:
            following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
            os.close(current)
            current = following
        opened = os.fstat(current)
        if not stat.S_ISDIR(opened.st_mode):
            raise OSError("path is not a directory")
        return current, opened
    except BaseException:
        os.close(current)
        raise


def _validate_lane_root(source_root: Path, command: dict[str, Any]) -> dict[str, Any]:
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
    approved_descriptor = lane_descriptor = -1
    try:
        approved_descriptor, _ = _open_absolute_directory_no_follow(approved_root)
        current = approved_descriptor
        for part in relative.parts:
            lane_descriptor = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
            if current != approved_descriptor:
                os.close(current)
            current = lane_descriptor
            lane_descriptor = -1
        lane_descriptor = current
        observed = os.fstat(lane_descriptor)
        if not stat.S_ISDIR(observed.st_mode):
            raise OSError("lane is not a directory")
        return {
            "device": observed.st_dev,
            "inode": observed.st_ino,
            "type": "DIRECTORY",
        }
    except OSError as exc:
        raise ControlledCoordinationError(
            "LANE_ROOT_UNSAFE",
            "approved root and lane must be existing no-follow directories",
        ) from exc
    finally:
        if lane_descriptor >= 0:
            os.close(lane_descriptor)
        if approved_descriptor >= 0 and approved_descriptor != lane_descriptor:
            os.close(approved_descriptor)


def _validate_live_bindings(
    repository_root: Path,
    source_root: Path,
    identity: dict[str, Any],
    command: dict[str, Any],
) -> dict[str, Any]:
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
    lane_identity = _validate_lane_root(source_root, command)
    try:
        live_snapshot = build_authority_snapshot(
            repository_root, loaded["integrationRoot"], source_root
        )
    except IntegrationAuthorityError as exc:
        raise ControlledCoordinationError(
            "LIVE_AUTHORITY_SNAPSHOT_INVALID",
            "registered integration could not rebuild a live authority snapshot",
        ) from exc
    if canonical_json_bytes(live_snapshot) != canonical_json_bytes(snapshot):
        raise ControlledCoordinationError(
            "LIVE_AUTHORITY_SNAPSHOT_MISMATCH",
            "supplied authority snapshot differs from the registered live rebuild",
        )
    development = live_snapshot["facts"].get("permission.development")
    if (
        not isinstance(development, dict)
        or development.get("normalizedValue") != "ALLOW"
    ):
        raise ControlledCoordinationError(
            "DEVELOPMENT_AUTHORITY_DENIED",
            "live project authority does not permit controlled development",
        )
    return lane_identity


def _is_nonterminal(lease: dict[str, Any]) -> bool:
    return not (
        lease["state"] in _TERMINAL_STATES and lease["released"] is True
    )


def _planning_graph(
    repository_root: Path,
    active_leases: list[dict[str, Any]],
    command: dict[str, Any],
) -> list[dict[str, Any]]:
    report = build_conflict_report(
        repository_root,
        project_id=command["projectId"],
        authority_snapshot_fingerprint=command["authoritySnapshotFingerprint"],
        conflict_policy_version=command["conflictPolicyVersion"],
        descriptors=command["planningRequest"]["slices"],
    )
    by_slice: dict[str, dict[str, Any]] = {}
    for footprint in [
        *(item for lease in active_leases for item in lease["planningFootprints"]),
        *report["footprints"],
    ]:
        prior = by_slice.get(footprint["sliceId"])
        if prior is not None and canonical_json_bytes(prior) != canonical_json_bytes(
            footprint
        ):
            raise ControlledCoordinationError(
                "ACTIVE_PLANNING_GRAPH_CHANGED",
                "the same slice identity has different authority-bound planning footprints",
            )
        by_slice[footprint["sliceId"]] = copy.deepcopy(footprint)
    return [by_slice[slice_id] for slice_id in sorted(by_slice)]


def _footprints_conflict(
    left: dict[str, Any],
    right: dict[str, Any],
    graph: list[dict[str, Any]],
) -> bool:
    return bool(
        _conflict_reasons(
            left,
            right,
            _dependency_closure(graph),
            _owner_closure(graph),
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


def _retired_recovery_identities(
    journal: dict[str, Any],
) -> tuple[set[str], set[str]]:
    lease_by_id = {lease["leaseId"]: lease for lease in journal["leases"]}
    retired_batches: set[str] = set()
    retired_attempts: set[str] = set()
    for receipt in journal["receipts"]:
        if receipt["receiptType"] != "RECOVERY":
            continue
        for lease_id in receipt["evidence"]["revokedLeaseIds"]:
            lease = lease_by_id.get(lease_id)
            if lease is None:
                raise ControlledCoordinationError(
                    "COORDINATOR_STATE_CORRUPT",
                    "recovery receipt retires a missing durable lease",
                )
            retired_batches.add(lease["batchPlanId"])
            retired_attempts.add(lease["attemptId"])
    return retired_batches, retired_attempts


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


def _lease_result_for_receipt(
    lease: dict[str, Any], receipt: dict[str, Any]
) -> dict[str, Any]:
    """Project one historical lease result from its durable authority receipt."""
    command = receipt.get("evidence", {}).get("command")
    if (
        not isinstance(command, dict)
        or receipt.get("projectExecutionKey") != lease.get("projectExecutionKey")
        or receipt.get("fencingToken") != lease.get("fencingToken")
        or command.get("authoritySnapshotFingerprint")
        != receipt.get("authoritySnapshotFingerprint")
        or receipt.get("commandDigest") != command.get("commandDigest")
    ):
        raise ControlledCoordinationError(
            "COORDINATOR_STATE_CORRUPT",
            "durable receipt is not associated with its lease",
        )
    result = copy.deepcopy(lease)
    if receipt.get("receiptType") == "ACQUIRE":
        if (
            receipt.get("previousState") is not None
            or receipt.get("nextState") != "ADMITTED"
            or receipt.get("authoritySnapshotFingerprint")
            != lease.get("authoritySnapshotFingerprint")
            or (
                command.get("batchPlanId"),
                command.get("sliceId"),
                command.get("attemptId"),
            )
            != (
                lease.get("batchPlanId"),
                lease.get("sliceId"),
                lease.get("attemptId"),
            )
            or receipt.get("recordedAt") != command.get("asOf")
        ):
            raise ControlledCoordinationError(
                "COORDINATOR_STATE_CORRUPT",
                "acquisition receipt is not associated with its lease",
            )
        result.update(
            {
                "state": "ADMITTED",
                "candidateIdentity": None,
                "acquiredAt": command["asOf"],
                "lastTransitionAt": command["asOf"],
                "released": False,
                "recoveryStatus": "CLEAR",
            }
        )
    elif receipt.get("receiptType") == "TRANSITION":
        proof = command.get("lifecycleAuthorityProof")
        if (
            not isinstance(proof, dict)
            or command.get("leaseId") != lease.get("leaseId")
            or command.get("attemptId") != lease.get("attemptId")
            or command.get("fencingToken") != lease.get("fencingToken")
            or receipt.get("previousState") != command.get("expectedState")
            or receipt.get("nextState") != command.get("nextState")
            or receipt.get("recordedAt") != proof.get("assertedAt")
        ):
            raise ControlledCoordinationError(
                "COORDINATOR_STATE_CORRUPT",
                "transition receipt is not associated with its lease",
            )
        result.update(
            {
                "state": receipt["nextState"],
                "candidateIdentity": copy.deepcopy(command.get("candidateIdentity")),
                "lastTransitionAt": receipt["recordedAt"],
                "released": receipt["nextState"] == "CLOSED",
                "recoveryStatus": "CLEAR",
            }
        )
    else:
        raise ControlledCoordinationError(
            "COORDINATOR_STATE_CORRUPT",
            "lease result requires an acquisition or transition receipt",
        )
    result["receiptId"] = receipt["receiptId"]
    result["journalVersion"] = receipt["nextJournalVersion"]
    result["leaseRetained"] = not result["released"]
    return result


def _transition_receipts_for(
    journal: dict[str, Any], lease_id: str
) -> list[dict[str, Any]]:
    return [
        receipt
        for receipt in journal["receipts"]
        if receipt["receiptType"] == "TRANSITION"
        and receipt["evidence"]["command"]["leaseId"] == lease_id
    ]


def _current_authority_record(
    snapshot: dict[str, Any],
    *,
    reference: str,
    digest: str,
    authority_id: str | None = None,
    code: str,
) -> dict[str, Any]:
    record = next(
        (item for item in snapshot["authorities"] if item["path"] == reference),
        None,
    )
    if (
        record is None
        or digest != "sha256:" + record["sha256"]
        or (authority_id is not None and record["id"] != authority_id)
    ):
        raise ControlledCoordinationError(
            code, "transition authority is absent from the current live snapshot"
        )
    return record


def _read_current_authority_bytes(
    source_root: Path, record: dict[str, Any]
) -> bytes:
    reference = Path(record["path"])
    if (
        reference.is_absolute()
        or not reference.parts
        or any(part in {"", ".", ".."} for part in reference.parts)
    ):
        raise ControlledCoordinationError(
            "AUTHORITY_PUBLIC_KEY_UNREADABLE",
            "authority public key reference is not a safe source-relative path",
        )
    root_descriptor = current_descriptor = file_descriptor = -1
    try:
        root_descriptor, _ = _open_absolute_directory_no_follow(source_root)
        current_descriptor = root_descriptor
        for part in reference.parts[:-1]:
            following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_descriptor)
            if current_descriptor != root_descriptor:
                os.close(current_descriptor)
            current_descriptor = following
        file_descriptor = os.open(
            reference.parts[-1],
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=current_descriptor,
        )
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 1024 * 1024:
            raise OSError("authority public key must be a bounded regular file")
        chunks: list[bytes] = []
        remaining = 1024 * 1024 + 1
        while remaining:
            chunk = os.read(file_descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        public_key = b"".join(chunks)
        after = os.fstat(file_descriptor)
        if (
            not _same_physical_identity(before, after)
            or len(public_key) > 1024 * 1024
            or sha256_bytes(public_key) != record["sha256"]
        ):
            raise OSError("authority public key changed during the locked read")
        return public_key
    except OSError as exc:
        raise ControlledCoordinationError(
            "AUTHORITY_PUBLIC_KEY_UNREADABLE",
            "current authority public key could not be read no-follow",
        ) from exc
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if current_descriptor >= 0 and current_descriptor != root_descriptor:
            os.close(current_descriptor)
        if root_descriptor >= 0:
            os.close(root_descriptor)


def _verified_ssh_keygen_path() -> str:
    if _SSH_KEYGEN_PATH != "/usr/bin/ssh-keygen":
        raise ControlledCoordinationError(
            "SSH_KEYGEN_VERIFIER_INVALID",
            "SSHSIG verifier path is not the fixed system path",
        )
    descriptor = -1
    try:
        descriptor = os.open(
            _SSH_KEYGEN_PATH,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or before.st_gid != 0
            or stat.S_IMODE(before.st_mode) & (stat.S_IWGRP | stat.S_IWOTH)
            or before.st_size > 16 * 1024 * 1024
        ):
            raise OSError("SSHSIG verifier ownership or mode is not trusted")
        chunks: list[bytes] = []
        remaining = 16 * 1024 * 1024 + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        executable = b"".join(chunks)
        after = os.fstat(descriptor)
        path_stat = os.stat(_SSH_KEYGEN_PATH, follow_symlinks=False)
        if (
            not _same_physical_identity(before, after)
            or not _same_physical_identity(before, path_stat)
            or after.st_uid != 0
            or after.st_gid != 0
            or stat.S_IMODE(after.st_mode) & (stat.S_IWGRP | stat.S_IWOTH)
            or len(executable) > 16 * 1024 * 1024
            or sha256_bytes(executable) != _SSH_KEYGEN_SHA256
        ):
            raise OSError("SSHSIG verifier changed or failed its pinned digest")
    except OSError as exc:
        raise ControlledCoordinationError(
            "SSH_KEYGEN_VERIFIER_INVALID",
            "fixed system SSHSIG verifier failed integrity checks",
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return "/usr/bin/ssh-keygen"


def _openssh_ed25519_public_key(public_key: bytes) -> bytes:
    try:
        parts = public_key.decode("ascii").strip().split()
    except UnicodeDecodeError as exc:
        raise ControlledCoordinationError(
            "AUTHORITY_PUBLIC_KEY_INVALID",
            "SSHSIG authority key must be canonical OpenSSH ASCII",
        ) from exc
    if len(parts) != 2 or parts[0] != "ssh-ed25519":
        raise ControlledCoordinationError(
            "AUTHORITY_PUBLIC_KEY_INVALID",
            "SSHSIG authority must contain exactly one OpenSSH Ed25519 public key",
        )
    return f"{parts[0]} {parts[1]}".encode("ascii")


def _verify_sshsig_signature(
    public_key: bytes,
    signature_text: str,
    payload: dict[str, Any],
    *,
    identity: str,
    namespace: str,
    invalid_code: str,
) -> None:
    verifier = _verified_ssh_keygen_path()
    canonical_public_key = _openssh_ed25519_public_key(public_key)
    try:
        signature = signature_text.encode("ascii")
        if _SSHSIG_ARMOR.fullmatch(signature) is None:
            raise UnicodeError("SSHSIG armor is not canonical")
        with tempfile.TemporaryDirectory(prefix="controlled-sshsig-verify-") as temporary:
            temporary_root = Path(temporary)
            allowed_signers_path = temporary_root / "allowed_signers"
            signature_path = temporary_root / "evidence.sig"
            allowed_signers_path.write_bytes(
                identity.encode("ascii") + b" " + canonical_public_key + b"\n"
            )
            signature_path.write_bytes(signature)
            allowed_signers_path.chmod(0o600)
            signature_path.chmod(0o600)
            completed = subprocess.run(
                [
                    verifier,
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed_signers_path),
                    "-I",
                    identity,
                    "-n",
                    namespace,
                    "-s",
                    str(signature_path),
                ],
                check=False,
                capture_output=True,
                input=canonical_json_bytes(payload),
                env={"LC_ALL": "C"},
                timeout=10,
            )
    except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
        raise ControlledCoordinationError(
            invalid_code, "fixed system ssh-keygen could not verify SSHSIG evidence"
        ) from exc
    if completed.returncode != 0:
        raise ControlledCoordinationError(
            invalid_code, "SSHSIG evidence is not valid for the fixed authority identity"
        )


def _lifecycle_signature_payload(command: dict[str, Any]) -> dict[str, Any]:
    proof = command["lifecycleAuthorityProof"]
    return {
        "schemaVersion": "controlled-lifecycle-signature-payload/v1",
        "authorityId": proof["authorityId"],
        "projectExecutionKey": command["projectExecutionKey"],
        "leaseId": command["leaseId"],
        "attemptId": command["attemptId"],
        "fencingToken": command["fencingToken"],
        "authoritySnapshotFingerprint": command["authoritySnapshotFingerprint"],
        "expectedState": command["expectedState"],
        "nextState": command["nextState"],
        "candidateIdentity": command["candidateIdentity"],
        "reviewBindingDigest": proof["reviewBindingDigest"],
        "reviewEvidenceDigest": proof["reviewEvidenceDigest"],
        "assertedAt": proof["assertedAt"],
    }


def _review_signature_payload(
    command: dict[str, Any],
    review: dict[str, Any],
    *,
    required_reviewers: list[str],
    minimum_review_verdict: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": "controlled-review-signature-payload/v1",
        "projectExecutionKey": command["projectExecutionKey"],
        "leaseId": command["leaseId"],
        "attemptId": command["attemptId"],
        "fencingToken": command["fencingToken"],
        "authoritySnapshotFingerprint": command["authoritySnapshotFingerprint"],
        "candidateIdentity": command["candidateIdentity"],
        "reviewerId": review["reviewerId"],
        "reviewerRole": review["reviewerRole"],
        "verdict": review["verdict"],
        "findingCounts": review["findingCounts"],
        "reviewedAt": review["reviewedAt"],
        "requiredReviewerPolicy": required_reviewers,
        "minimumReviewVerdict": minimum_review_verdict,
    }


def _acquired_review_policy(
    acquire_command: dict[str, Any], lease: dict[str, Any]
) -> tuple[list[str], str]:
    plan = acquire_command["executionPlan"]
    requirements = plan["executionRequirements"]
    slice_requirements = [
        item
        for item in requirements["sliceRequirements"]
        if item["sliceId"] == lease["sliceId"]
    ]
    required_reviewers = requirements["requiredReviewers"]
    minimum_verdict = requirements["minimumReviewVerdict"]
    if (
        len(slice_requirements) != 1
        or required_reviewers != sorted(set(required_reviewers))
        or not required_reviewers
        or slice_requirements[0]["reviewPolicy"]["reviewerRole"]
        not in required_reviewers
        or slice_requirements[0]["reviewPolicy"]["minimumVerdict"]
        != minimum_verdict
    ):
        raise ControlledCoordinationError(
            "REVIEWER_POLICY_MISMATCH",
            "acquired execution plan has no complete reviewer policy for the lane",
        )
    return list(required_reviewers), minimum_verdict


def _review_binding_digest(
    command: dict[str, Any], review: dict[str, Any]
) -> str:
    return _sha256(
        {
            "candidateIdentity": command["candidateIdentity"],
            "projectExecutionKey": command["projectExecutionKey"],
            "leaseId": command["leaseId"],
            "attemptId": command["attemptId"],
            "fencingToken": command["fencingToken"],
            "authoritySnapshotFingerprint": command[
                "authoritySnapshotFingerprint"
            ],
            "reviewerId": review["reviewerId"],
            "reviewerRole": review["reviewerRole"],
            "reviewerAuthorityReference": review["reviewerAuthorityReference"],
            "reviewerAuthorityDigest": review["reviewerAuthorityDigest"],
        }
    )


def _validate_and_verify_review_set(
    source_root: Path,
    live_snapshot: dict[str, Any],
    acquire_command: dict[str, Any],
    lease: dict[str, Any],
    command: dict[str, Any],
) -> None:
    reviews = command["reviewEvidenceSet"]
    proof = command["lifecycleAuthorityProof"]
    required_reviewers, minimum_verdict = _acquired_review_policy(
        acquire_command, lease
    )
    roles = [review["reviewerRole"] for review in reviews]
    reviewer_ids = [review["reviewerId"] for review in reviews]
    if (
        roles != required_reviewers
        or len(roles) != len(set(roles))
        or len(reviewer_ids) != len(set(reviewer_ids))
    ):
        raise ControlledCoordinationError(
            "REVIEWER_POLICY_MISMATCH",
            "review evidence roles do not exactly match the acquired execution plan",
        )

    expected_bindings: list[dict[str, Any]] = []
    for review in reviews:
        binding_digest = _review_binding_digest(command, review)
        expected_evidence_digest = _sha256(
            {
                key: value
                for key, value in review.items()
                if key not in {"signature", "evidenceDigest"}
            }
        )
        try:
            reviewed_at = datetime.fromisoformat(
                review["reviewedAt"].replace("Z", "+00:00")
            )
            asserted_at = datetime.fromisoformat(
                proof["assertedAt"].replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ControlledCoordinationError(
                "REVIEWER_POLICY_MISMATCH",
                "review evidence time is not valid for lifecycle verification",
            ) from exc
        if (
            review["reviewerId"] != review["reviewerRole"]
            or review["candidateIdentity"] != command["candidateIdentity"]
            or review["candidateIdentity"] != lease["candidateIdentity"]
            or review["projectExecutionKey"] != lease["projectExecutionKey"]
            or review["leaseId"] != lease["leaseId"]
            or review["attemptId"] != lease["attemptId"]
            or review["fencingToken"] != lease["fencingToken"]
            or review["authoritySnapshotFingerprint"]
            != live_snapshot["snapshotFingerprint"]
            or review["verdict"] != minimum_verdict
            or review["findingCounts"] != {"p0": 0, "p1": 0, "p2": 0}
            or reviewed_at > asserted_at
            or review["reviewBindingDigest"] != binding_digest
            or review["evidenceDigest"] != expected_evidence_digest
        ):
            raise ControlledCoordinationError(
                "REVIEWER_POLICY_MISMATCH",
                "review evidence does not satisfy the acquired candidate policy",
            )
        binding = {
            "reviewerRole": review["reviewerRole"],
            "reviewerId": review["reviewerId"],
            "reviewerAuthorityReference": review["reviewerAuthorityReference"],
            "reviewerAuthorityDigest": review["reviewerAuthorityDigest"],
            "reviewBindingDigest": binding_digest,
        }
        expected_bindings.append(binding)
        reviewer_authority = _current_authority_record(
            live_snapshot,
            reference=review["reviewerAuthorityReference"],
            digest=review["reviewerAuthorityDigest"],
            authority_id=review["reviewerId"],
            code="REVIEWER_AUTHORITY_NOT_CURRENT",
        )
        reviewer_public_key = _read_current_authority_bytes(
            source_root, reviewer_authority
        )
        _verify_sshsig_signature(
            reviewer_public_key,
            review["signature"],
            _review_signature_payload(
                command,
                review,
                required_reviewers=required_reviewers,
                minimum_review_verdict=minimum_verdict,
            ),
            identity=review["reviewerId"],
            namespace=_REVIEW_SIGNATURE_NAMESPACE,
            invalid_code="REVIEW_SIGNATURE_INVALID",
        )

    if (
        proof["reviewerAuthorityBindings"] != expected_bindings
        or proof["reviewBindingDigest"]
        != _sha256([binding["reviewBindingDigest"] for binding in expected_bindings])
        or proof["reviewEvidenceDigest"] != _sha256(reviews)
    ):
        raise ControlledCoordinationError(
            "REVIEWER_POLICY_MISMATCH",
            "lifecycle proof does not aggregate the complete review evidence set",
        )


def _validate_lane_physical_identity(lease: dict[str, Any]) -> None:
    descriptor = -1
    try:
        descriptor, observed = _open_absolute_directory_no_follow(
            Path(lease["laneRoot"])
        )
    except OSError as exc:
        raise ControlledCoordinationError(
            "LANE_ROOT_IDENTITY_CHANGED",
            "leased lane root is no longer an existing no-follow directory",
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    durable = lease["lanePhysicalIdentity"]
    if (
        observed.st_dev != durable["device"]
        or observed.st_ino != durable["inode"]
        or not stat.S_ISDIR(observed.st_mode)
        or durable["type"] != "DIRECTORY"
    ):
        raise ControlledCoordinationError(
            "LANE_ROOT_IDENTITY_CHANGED",
            "leased lane root no longer has its durable physical identity",
        )


def _validate_live_lane_candidate(
    lease: dict[str, Any], candidate: dict[str, Any]
) -> None:
    lane_root = Path(lease["laneRoot"])
    lane_descriptor = -1
    boundary = None
    try:
        try:
            lane_descriptor, observed = _open_absolute_directory_no_follow(lane_root)
        except OSError as exc:
            raise ControlledCoordinationError(
                "LANE_ROOT_IDENTITY_CHANGED",
                "leased lane root is no longer an existing no-follow directory",
            ) from exc
        durable = lease["lanePhysicalIdentity"]
        lane_identity = (observed.st_dev, observed.st_ino, stat.S_IFMT(observed.st_mode))
        if lane_identity != (
            durable["device"],
            durable["inode"],
            stat.S_IFDIR,
        ) or durable["type"] != "DIRECTORY":
            raise ControlledCoordinationError(
                "LANE_ROOT_IDENTITY_CHANGED",
                "leased lane root no longer has its durable physical identity",
            )
        boundary = _open_git_boundary(
            lane_descriptor,
            lane_root,
            lane_identity,
            error_code="LANE_CANDIDATE_INVALID",
            error_message="candidate-bound lane Git identity is not physically sealed",
        )
        top_level = str(lane_root)
        live_head = _read_git_head(boundary)
        commit = candidate["commit"]
        commit_body = _read_git_object(
            boundary, commit, expected_type="commit"
        )
        header, separator, _message = commit_body.partition(b"\n\n")
        if not separator:
            raise ValueError("candidate commit has no canonical header terminator")
        tree_values: list[str] = []
        parents: list[str] = []
        for line in header.splitlines():
            if line.startswith(b"tree "):
                tree_values.append(
                    line.removeprefix(b"tree ").decode("ascii", "strict")
                )
            elif line.startswith(b"parent "):
                parents.append(line.removeprefix(b"parent ").decode("ascii", "strict"))
        if len(tree_values) != 1 or len(parents) != 1:
            raise ValueError("candidate commit must have exactly one tree and parent")
        tree = tree_values[0]
        _read_git_object(boundary, parents[0], expected_type="commit")
        _read_git_object(boundary, tree, expected_type="tree")
    except (ControlledCoordinationError, OSError, ValueError) as exc:
        if isinstance(exc, ControlledCoordinationError) and exc.code in {
            "LANE_CANDIDATE_INVALID",
            "LANE_ROOT_IDENTITY_CHANGED",
        }:
            raise
        raise ControlledCoordinationError(
            "LANE_CANDIDATE_INVALID",
            "candidate-bound lane Git evidence is not readable",
        ) from exc
    finally:
        _close_git_boundary(boundary)
        if lane_descriptor >= 0:
            os.close(lane_descriptor)
    if (
        top_level != str(lane_root)
        or live_head != candidate["commit"]
        or commit != candidate["commit"]
        or len(parents) != 1
        or parents[0] != candidate["parent"]
        or tree != candidate["tree"]
    ):
        raise ControlledCoordinationError(
            "LANE_CANDIDATE_INVALID",
            "live lane must exactly reproduce Candidate/Parent/Tree identity",
        )


def _rebuild_transition_snapshot(
    repository_root: Path,
    source_root: Path,
    identity: dict[str, Any],
    acquire_command: dict[str, Any],
) -> dict[str, Any]:
    if resolve_project_execution_identity(repository_root, source_root) != identity:
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
    if (
        Path(loaded["sourceRoot"]).resolve() != source_root
        or registration["sourceAccess"] != "READ_ONLY"
        or registration["integrationId"] != integration["id"]
        or integration["projectId"] != acquire_command["projectId"]
    ):
        raise ControlledCoordinationError(
            "LIVE_AUTHORITY_BINDING_MISMATCH",
            "registration, integration, source, and acquisition identities changed",
        )
    try:
        snapshot = build_authority_snapshot(
            repository_root, loaded["integrationRoot"], source_root
        )
    except IntegrationAuthorityError as exc:
        raise ControlledCoordinationError(
            "LIVE_AUTHORITY_SNAPSHOT_INVALID",
            "registered integration could not rebuild a live authority snapshot",
        ) from exc
    if snapshot["projectId"] != acquire_command["projectId"]:
        raise ControlledCoordinationError(
            "LIVE_AUTHORITY_BINDING_MISMATCH",
            "current authority snapshot belongs to another project",
        )
    return snapshot


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
                replay_lane_identity = _validate_live_bindings(
                    repository, source, identity, normalized_replay
                )
                if replay_lane_identity != existing["lanePhysicalIdentity"]:
                    raise ControlledCoordinationError(
                        "LANE_ROOT_IDENTITY_CHANGED",
                        "replayed lane root no longer has its leased physical identity",
                    )
                if canonical_json_bytes(receipt["evidence"]["command"]) != canonical_json_bytes(
                    normalized_replay
                ):
                    raise ControlledCoordinationError(
                        "ACQUISITION_IDEMPOTENCY_CONFLICT",
                        "the acquisition idempotency key payload changed",
                    )
                return _lease_result_for_receipt(existing, receipt)

            normalized = normalize_acquire_command(repository, raw)
            retired_batches, retired_attempts = _retired_recovery_identities(current)
            if (
                normalized["batchPlanId"] in retired_batches
                or normalized["attemptId"] in retired_attempts
            ):
                raise ControlledCoordinationError(
                    "RECOVERED_PLAN_IDENTITY_REUSED",
                    "recovery permanently retired this batch or attempt identity",
                )
            lane_identity = _validate_live_bindings(
                repository, source, identity, normalized
            )
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
            if any(
                lease["lanePhysicalIdentity"] == lane_identity
                or lease["laneRoot"] == normalized["laneRoot"]
                for lease in active
            ):
                raise ControlledCoordinationError(
                    "LANE_ROOT_CONFLICT", "lane roots are exclusive across nonterminal leases"
                )
            planning_graph = _planning_graph(repository, active, normalized)
            if any(
                _footprints_conflict(
                    lease["fullFootprint"],
                    normalized["fullFootprint"],
                    planning_graph,
                )
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
            if _validate_lane_root(source, normalized) != lane_identity:
                raise ControlledCoordinationError(
                    "LANE_ROOT_IDENTITY_CHANGED",
                    "lane root identity changed before lease persistence",
                )
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
                "planningFootprints": [
                    copy.deepcopy(item)
                    for item in planning_graph
                    if item["sliceId"]
                    in {
                        descriptor["sliceId"]
                        for descriptor in normalized["planningRequest"]["slices"]
                    }
                ],
                "originalSourceRoot": normalized["originalSourceRoot"],
                "laneRoot": normalized["laneRoot"],
                "lanePhysicalIdentity": lane_identity,
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
            return _lease_result_for_receipt(persisted_lease, receipt)


def transition_lane_lease(
    repository_root: Path,
    source_root: Path,
    command: dict[str, object],
) -> dict[str, object]:
    """Apply one project-authorized, fenced lease transition under the project CAS."""
    repository = Path(repository_root).resolve()
    source = Path(source_root).resolve()
    identity = resolve_project_execution_identity(repository, source_root)
    project_execution_key = identity["projectExecutionKey"]
    with CoordinatorStateStore.open(identity) as store:
        with store.exclusive_project_lock():
            observed = store.read_journal()
            if observed is None:
                raise ControlledCoordinationError(
                    "COORDINATOR_LEASE_NOT_FOUND",
                    "cannot transition a lease before coordinator acquisition",
                )
            current = copy.deepcopy(observed)
            normalized = normalize_transition_command(repository, copy.deepcopy(command))
            if normalized["projectExecutionKey"] != project_execution_key:
                raise ControlledCoordinationError(
                    "PROJECT_EXECUTION_KEY_MISMATCH",
                    "transition command belongs to another project execution key",
                )
            lease = next(
                (
                    item
                    for item in current["leases"]
                    if item["leaseId"] == normalized["leaseId"]
                ),
                None,
            )
            if lease is None:
                raise ControlledCoordinationError(
                    "COORDINATOR_LEASE_NOT_FOUND", "transition lease is not durable"
                )

            prior_transitions = _transition_receipts_for(current, lease["leaseId"])
            exact_replay = next(
                (
                    receipt
                    for receipt in prior_transitions
                    if receipt["commandDigest"] == normalized["commandDigest"]
                    and canonical_json_bytes(receipt["evidence"]["command"])
                    == canonical_json_bytes(normalized)
                ),
                None,
            )
            conflicting_replay = next(
                (
                    receipt
                    for receipt in prior_transitions
                    if (
                        receipt["previousState"],
                        receipt["nextState"],
                    )
                    == (normalized["expectedState"], normalized["nextState"])
                ),
                None,
            )

            if current["recoveryState"] != "CLEAR":
                raise ControlledCoordinationError(
                    "COORDINATOR_RECOVERY_REQUIRED",
                    "project coordinator recovery must close before lease transition",
                )
            if lease["attemptId"] != normalized["attemptId"]:
                raise ControlledCoordinationError(
                    "LEASE_ATTEMPT_MISMATCH",
                    "transition attempt does not own the durable lease",
                )
            if lease["fencingToken"] != normalized["fencingToken"]:
                raise ControlledCoordinationError(
                    "STALE_FENCING_TOKEN",
                    "transition fencing token is not current for the durable lease",
                )

            acquire_receipt = _acquire_receipt_for(current, lease)
            if acquire_receipt is None:
                raise ControlledCoordinationError(
                    "COORDINATOR_STATE_CORRUPT",
                    "durable lease has no acquisition authority receipt",
                )
            acquire_command = acquire_receipt["evidence"]["command"]
            if lease["originalSourceRoot"] != str(source):
                raise ControlledCoordinationError(
                    "LIVE_AUTHORITY_BINDING_MISMATCH",
                    "transition source does not own the durable lease",
                )
            live_snapshot = _rebuild_transition_snapshot(
                repository, source, identity, acquire_command
            )
            live_fingerprint = live_snapshot["snapshotFingerprint"]
            authority_drifted = live_fingerprint != lease["authoritySnapshotFingerprint"]
            if normalized["authoritySnapshotFingerprint"] != live_fingerprint:
                raise ControlledCoordinationError(
                    "LIVE_AUTHORITY_SNAPSHOT_MISMATCH",
                    "transition fingerprint is not the current live authority snapshot",
                )
            if authority_drifted and normalized["nextState"] not in _REVOCATION_STATES:
                raise ControlledCoordinationError(
                    "AUTHORITY_SNAPSHOT_DRIFT",
                    "authority drift requires explicit stale or cancelled revocation",
                )

            proof = normalized["lifecycleAuthorityProof"]
            if proof["authorityId"] != "lifecycle-controller":
                raise ControlledCoordinationError(
                    "LIFECYCLE_AUTHORITY_NOT_CURRENT",
                    "transition proof is not issued by the lifecycle controller",
                )
            lifecycle_authority = _current_authority_record(
                live_snapshot,
                reference=proof["authorityReference"],
                digest=proof["authorityDigest"],
                authority_id="lifecycle-controller",
                code="LIFECYCLE_AUTHORITY_NOT_CURRENT",
            )
            lifecycle_public_key = _read_current_authority_bytes(
                source, lifecycle_authority
            )
            _verify_sshsig_signature(
                lifecycle_public_key,
                proof["signature"],
                _lifecycle_signature_payload(normalized),
                identity="lifecycle-controller",
                namespace=_LIFECYCLE_SIGNATURE_NAMESPACE,
                invalid_code="LIFECYCLE_SIGNATURE_INVALID",
            )
            if normalized["nextState"] == "REVIEW_GO":
                if normalized["candidateIdentity"] != lease["candidateIdentity"]:
                    raise ControlledCoordinationError(
                        "CANDIDATE_IDENTITY_MISMATCH",
                        "Candidate/Parent/Tree identity changed after fixation",
                    )
                _validate_and_verify_review_set(
                    source,
                    live_snapshot,
                    acquire_command,
                    lease,
                    normalized,
                )
            if exact_replay is not None:
                replay_candidate = normalized["candidateIdentity"]
                if replay_candidate is not None:
                    _validate_live_lane_candidate(lease, replay_candidate)
                return _lease_result_for_receipt(lease, exact_replay)
            if conflicting_replay is not None:
                raise ControlledCoordinationError(
                    "TRANSITION_IDEMPOTENCY_CONFLICT",
                    "a transition edge is already bound to another command payload",
                )
            if lease["state"] in _TERMINAL_STATES or lease["released"]:
                raise ControlledCoordinationError(
                    "TERMINAL_LEASE_IMMUTABLE",
                    "terminal lease state cannot be changed",
                )
            if lease["state"] != normalized["expectedState"]:
                raise ControlledCoordinationError(
                    "LEASE_STATE_MISMATCH",
                    "transition expected state is not the durable current state",
                )
            if normalized["nextState"] not in _ALLOWED_LEASE_TRANSITIONS.get(
                lease["state"], frozenset()
            ):
                raise ControlledCoordinationError(
                    "INVALID_STATE_TRANSITION",
                    f"transition {lease['state']} -> {normalized['nextState']} is not allowed",
                )

            if lease["candidateIdentity"] is None:
                if normalized["nextState"] == "FIXED_CANDIDATE":
                    next_candidate = copy.deepcopy(normalized["candidateIdentity"])
                elif normalized["candidateIdentity"] is None:
                    next_candidate = None
                else:
                    raise ControlledCoordinationError(
                        "CANDIDATE_IDENTITY_MISMATCH",
                        "candidate identity cannot appear before FIXED_CANDIDATE",
                    )
            else:
                if normalized["candidateIdentity"] != lease["candidateIdentity"]:
                    raise ControlledCoordinationError(
                        "CANDIDATE_IDENTITY_MISMATCH",
                        "Candidate/Parent/Tree identity changed after fixation",
                    )
                next_candidate = copy.deepcopy(lease["candidateIdentity"])
            if (
                normalized["nextState"] in _CANDIDATE_STATES
                and next_candidate is None
            ):
                raise ControlledCoordinationError(
                    "CANDIDATE_IDENTITY_REQUIRED",
                    "candidate identity is required for candidate-bound lifecycle states",
                )
            if next_candidate is not None:
                _validate_live_lane_candidate(lease, next_candidate)

            release = normalized["nextState"] == "CLOSED"
            if release and normalized["processQuiescence"]["processIds"]:
                raise ControlledCoordinationError(
                    "PROCESS_NOT_QUIESCENT",
                    "closed capacity release requires empty live process evidence",
                )

            previous_version = current["journalVersion"]
            next_version = previous_version + 1
            lease["state"] = normalized["nextState"]
            lease["candidateIdentity"] = next_candidate
            lease["lastTransitionAt"] = proof["assertedAt"]
            lease["released"] = release
            if normalized["nextState"] in _REVOCATION_STATES or authority_drifted:
                current["nextFencingToken"] = max(
                    current["nextFencingToken"], lease["fencingToken"] + 1
                )
            current["journalVersion"] = next_version
            receipt = {
                "schemaVersion": "controlled-coordinator-receipt/v1",
                "receiptId": _stable_id(
                    "coordinator-receipt",
                    {
                        "projectExecutionKey": project_execution_key,
                        "journalVersion": next_version,
                        "commandDigest": normalized["commandDigest"],
                        "fencingToken": lease["fencingToken"],
                    },
                ),
                "receiptType": "TRANSITION",
                "projectExecutionKey": project_execution_key,
                "previousJournalVersion": previous_version,
                "nextJournalVersion": next_version,
                "commandDigest": normalized["commandDigest"],
                "fencingToken": lease["fencingToken"],
                "previousState": normalized["expectedState"],
                "nextState": normalized["nextState"],
                "authoritySnapshotFingerprint": normalized[
                    "authoritySnapshotFingerprint"
                ],
                "journalDigest": "sha256:" + "0" * 64,
                "recordedAt": proof["assertedAt"],
                "evidence": {"command": normalized},
            }
            current["receipts"].append(receipt)
            receipt["journalDigest"] = _journal_digest(
                current, len(current["receipts"]) - 1
            )
            persisted = store.replace_journal(previous_version, current, receipt)
            persisted_lease = next(
                item
                for item in persisted["leases"]
                if item["leaseId"] == lease["leaseId"]
            )
            if persisted_lease != lease or persisted["receipts"][-1] != receipt:
                raise ControlledCoordinationError(
                    "COORDINATOR_POST_WRITE_MISMATCH",
                    "persisted transition did not reproduce lease and receipt",
                )
            return _lease_result_for_receipt(persisted_lease, receipt)
