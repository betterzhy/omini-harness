from __future__ import annotations

import copy
import os
import stat
import subprocess
from pathlib import Path
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
                return copy.deepcopy(existing)

            normalized = normalize_acquire_command(repository, raw)
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
            return copy.deepcopy(persisted_lease)
