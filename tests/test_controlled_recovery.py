from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from evolution_harness import controlled_coordinator as coordinator
from evolution_harness import controlled_write_guard as guard
from evolution_harness.authority import build_authority_snapshot
from evolution_harness.controlled_coordinator_inputs import (
    ControlledCoordinationError,
)
from evolution_harness.controlled_recovery import (
    observe_lane_writes,
    record_project_recovery,
)
from evolution_harness.coordinator_state import CoordinatorStateStore
from evolution_harness.hashing import canonical_json_bytes, sha256_bytes
from test_controlled_coordinator_acquire import AcquisitionFactory, _committed_source
from test_controlled_coordinator_lifecycle import (
    _acquire,
    _advance,
    _transition_command,
)
from test_controlled_write_guard import WRITER, _persist_active_lease


_SSH_KEYGEN = "/usr/bin/ssh-keygen"
_RECOVERY_NAMESPACE = "agent-evolution-controlled-recovery-v1"


def _sha256(value: object) -> str:
    return "sha256:" + sha256_bytes(canonical_json_bytes(value))


def _command_digest(command: dict[str, object]) -> dict[str, object]:
    command["commandDigest"] = _sha256(
        {key: value for key, value in command.items() if key != "commandDigest"}
    )
    return command


def _receipt_id(receipt: dict[str, object]) -> str:
    return "coordinator-receipt:" + sha256_bytes(
        canonical_json_bytes(
            {
                "projectExecutionKey": receipt["projectExecutionKey"],
                "journalVersion": receipt["nextJournalVersion"],
                "commandDigest": receipt["commandDigest"],
                "fencingToken": receipt["fencingToken"],
            }
        )
    )[:24]


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _public_key(private_key: Path) -> str:
    parts = Path(str(private_key) + ".pub").read_text(encoding="utf-8").split()
    return f"{parts[0]} {parts[1]}\n"


def _sign(private_key: Path, payload: object, namespace: str) -> str:
    with tempfile.TemporaryDirectory(prefix="task6-signing-payload-") as temporary:
        payload_path = Path(temporary) / "payload.json"
        payload_path.write_bytes(canonical_json_bytes(payload))
        subprocess.run(
            [
                _SSH_KEYGEN,
                "-Y",
                "sign",
                "-f",
                str(private_key),
                "-n",
                namespace,
                str(payload_path),
            ],
            check=True,
            capture_output=True,
        )
        return Path(str(payload_path) + ".sig").read_text(encoding="ascii")


@pytest.fixture
def recovery_factory(tmp_path, monkeypatch, repository_root, controlled_factory):
    monkeypatch.setenv(
        "AGENT_EVOLUTION_COORDINATOR_ROOT", str(tmp_path / "coordinator-state")
    )
    source = _committed_source(
        repository_root, tmp_path / "external-project", controlled_factory
    )
    factory = AcquisitionFactory(repository_root, source, controlled_factory)
    for private_name, public_name in (
        ("lifecycle-private.pem", "lifecycle-authority-public.pem"),
        ("recovery-private.pem", "recovery-authority-public.pem"),
        ("wrong-recovery-private.pem", "wrong-recovery-public.pem"),
    ):
        private_path = tmp_path / private_name
        subprocess.run(
            [
                _SSH_KEYGEN,
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-f",
                str(private_path),
            ],
            check=True,
        )
        (source / public_name).write_text(
            _public_key(private_path), encoding="utf-8"
        )
    (source / ".gitignore").write_text(".ignored/\nbuild/\n", encoding="utf-8")
    _git(
        source,
        "add",
        ".gitignore",
        "lifecycle-authority-public.pem",
        "recovery-authority-public.pem",
        "wrong-recovery-public.pem",
    )
    _git(source, "commit", "-qm", "test recovery authorities")
    factory.lifecycle_private_key = tmp_path / "lifecycle-private.pem"
    factory.recovery_private_key = tmp_path / "recovery-private.pem"
    factory.wrong_recovery_private_key = tmp_path / "wrong-recovery-private.pem"
    return factory


def _journal(factory) -> dict[str, object]:
    return factory.journal()


def _observation_command(
    lease: dict[str, object],
    observed_paths: list[str],
    *,
    before_digest: str | None = None,
    ephemeral_paths_removed: list[str] | None = None,
    process_ids: list[int] | None = None,
    observed_at: str = "2026-08-13T13:00:00Z",
) -> dict[str, object]:
    inventory, _, remaining_ephemeral = guard._complete_persistent_breach_inventory(
        lease
    )
    assert remaining_ephemeral == []
    return _command_digest(
        {
            "schemaVersion": "controlled-write-observation-command/v1",
            "projectExecutionKey": lease["projectExecutionKey"],
            "leaseId": lease["leaseId"],
            "fencingToken": lease["fencingToken"],
            "beforeInventoryDigest": before_digest or _sha256(inventory),
            "observedPaths": sorted(observed_paths),
            "ephemeralPathsRemoved": sorted(
                ephemeral_paths_removed
                if ephemeral_paths_removed is not None
                else lease["fullFootprint"]["ephemeralWriteSet"]
            ),
            "processQuiescence": {
                "status": "QUIESCENT",
                "observedAt": observed_at,
                "processIds": process_ids or [],
            },
        }
    )


def _current_authority(factory, authority_id: str) -> tuple[dict, dict]:
    snapshot = build_authority_snapshot(
        factory.repository_root,
        factory.repository_root / "integrations/neutral-shadow",
        factory.source_root,
    )
    authority = next(
        item for item in snapshot["authorities"] if item["id"] == authority_id
    )
    return snapshot, authority


def _recovery_signature_payload(command: dict[str, object]) -> dict[str, object]:
    return {
        key: copy.deepcopy(value)
        for key, value in command.items()
        if key not in {"signature", "commandDigest"}
    }


def _recovery_command(
    factory,
    *,
    recovery_id: str = "recovery:" + "a" * 24,
    private_key: Path | None = None,
) -> dict[str, object]:
    journal = _journal(factory)
    evidence = journal["recoveryEvidence"]
    assert journal["recoveryState"] == "PROJECT_WRITESET_RECOVERY"
    assert isinstance(evidence, dict)
    _, authority = _current_authority(factory, "recovery-controller")
    lease_by_id = {item["leaseId"]: item for item in journal["leases"]}
    command = {
        "schemaVersion": "controlled-recovery-command/v1",
        "projectExecutionKey": journal["projectExecutionKey"],
        "recoveryId": recovery_id,
        "recoveryAuthorityId": "recovery-controller",
        "recoveryAuthorityReference": authority["path"],
        "recoveryAuthorityDigest": "sha256:" + authority["sha256"],
        "recoveryAuthorityPublicKey": Path(
            factory.source_root, authority["path"]
        ).read_text(encoding="ascii"),
        "signatureAlgorithm": "ED25519",
        "signatureFormat": "OPENSSH_SSHSIG_V1",
        "expectedJournalVersion": journal["journalVersion"],
        "processQuiescenceProofs": [
            {
                "leaseId": lease_id,
                "fencingToken": lease_by_id[lease_id]["fencingToken"],
                "status": "QUIESCENT",
                "observedAt": "2026-08-13T13:01:00Z",
            }
            for lease_id in evidence["revokedLeaseIds"]
        ],
        "observedWriteSet": copy.deepcopy(evidence["observedWriteSet"]),
        "affectedLeaseDecisions": copy.deepcopy(
            evidence["affectedLeaseDecisions"]
        ),
        "replacementPlanRequired": True,
    }
    command["signature"] = _sign(
        private_key or factory.recovery_private_key,
        _recovery_signature_payload(command),
        _RECOVERY_NAMESPACE,
    )
    return _command_digest(command)


def _observe(factory, lease, paths, **changes):
    command = _observation_command(lease, paths, **changes)
    return observe_lane_writes(
        factory.repository_root, factory.source_root, command
    ), command


def _untracked_breach(lease: dict[str, object], name: str = "breach.txt") -> str:
    lane = Path(lease["laneRoot"])
    (lane / name).write_text("undeclared\n", encoding="utf-8")
    return name


def _two_disjoint_leases(factory):
    first = _acquire(factory)
    second = _acquire(
        factory,
        slice_id="slice:neutral-b",
        attempt_id="attempt:neutral-b",
        owner="owner:neutral-b",
        exact_write_set="services/neutral-b",
    )
    return first, second


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("empty-breach", "WRITE_OBSERVATION_EMPTY"),
        ("before-inventory", "OBSERVATION_INVENTORY_MISMATCH"),
        ("ephemeral-set", "OBSERVATION_EPHEMERAL_SET_MISMATCH"),
        ("process-ids", "PROCESS_NOT_QUIESCENT"),
    ],
)
def test_new_public_observation_requires_complete_live_evidence(
    recovery_factory, mutation, code
):
    lease = _acquire(recovery_factory)
    observed_paths: list[str] = []
    if mutation != "empty-breach":
        observed_paths = [_untracked_breach(lease)]
    command = _observation_command(lease, observed_paths)
    if mutation == "before-inventory":
        command["beforeInventoryDigest"] = _sha256({"forged": True})
    elif mutation == "ephemeral-set":
        command["ephemeralPathsRemoved"] = []
    elif mutation == "process-ids":
        command["processQuiescence"]["processIds"] = [4242]
    _command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        observe_lane_writes(
            recovery_factory.repository_root,
            recovery_factory.source_root,
            command,
        )
    assert caught.value.code == code


def test_observation_exact_replay_precedes_live_empty_revalidation(recovery_factory):
    lease = _acquire(recovery_factory)
    breach = _untracked_breach(lease)
    first, command = _observe(recovery_factory, lease, [breach])
    Path(lease["laneRoot"], breach).unlink()

    replay = observe_lane_writes(
        recovery_factory.repository_root,
        recovery_factory.source_root,
        command,
    )

    assert replay == first


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("tracked", ["private/secret.md"]),
        ("untracked", ["breach.txt"]),
        ("ignored", [".ignored"]),
        ("deleted", ["release-control.yaml"]),
        ("renamed", ["moved-secret.md", "private", "private/secret.md"]),
        ("type-changed", ["private/secret.md"]),
    ],
)
def test_public_observation_requires_complete_live_persistent_breach_set(
    recovery_factory, mutation, expected
):
    lease = _acquire(recovery_factory)
    lane = Path(lease["laneRoot"])
    if mutation == "tracked":
        (lane / "private/secret.md").write_text("changed\n", encoding="utf-8")
    elif mutation == "untracked":
        _untracked_breach(lease)
    elif mutation == "ignored":
        (lane / ".ignored").mkdir()
        (lane / ".ignored/leak.txt").write_text("ignored\n", encoding="utf-8")
    elif mutation == "deleted":
        (lane / "release-control.yaml").unlink()
    elif mutation == "renamed":
        (lane / "private/secret.md").rename(lane / "moved-secret.md")
    else:
        os.chmod(lane / "private/secret.md", 0o755)

    incomplete = _observation_command(lease, expected[:-1])
    with pytest.raises(ControlledCoordinationError) as caught:
        observe_lane_writes(
            recovery_factory.repository_root,
            recovery_factory.source_root,
            incomplete,
        )
    assert caught.value.code == "OBSERVED_WRITESET_MISMATCH"

    result, _ = _observe(recovery_factory, lease, expected)
    assert result["recoveryState"] == "PROJECT_WRITESET_RECOVERY"
    assert result["observedWriteSet"] == expected


def test_complete_public_observation_includes_preexisting_empty_directory(
    recovery_factory
):
    lease = _acquire(recovery_factory)
    empty = Path(lease["laneRoot"], "preexisting-empty")
    empty.mkdir()

    inventory, breaches, remaining_ephemeral = (
        guard._complete_persistent_breach_inventory(lease)
    )

    assert inventory["paths"] == ["preexisting-empty"]
    assert inventory["untrackedPaths"] == ["preexisting-empty"]
    assert breaches == ["preexisting-empty"]
    assert remaining_ephemeral == []


def test_authority_path_breach_marks_every_affected_lease_stale(recovery_factory):
    first, second = _two_disjoint_leases(recovery_factory)
    Path(first["laneRoot"], "status.md").write_text(
        "ProjectStage = DELIVERY\nDevelopmentAuthorization = YES_CHANGED\n",
        encoding="utf-8",
    )

    result, _ = _observe(recovery_factory, first, ["status.md"])

    assert result["revokedLeaseIds"] == sorted(
        [first["leaseId"], second["leaseId"]]
    )
    expected = [
        {
            "leaseId": first["leaseId"],
            "decision": "STALE",
            "reason": "AUTHORITY_AFFECTED",
        },
        {
            "leaseId": second["leaseId"],
            "decision": "STALE",
            "reason": "AUTHORITY_AFFECTED",
        },
    ]
    assert result["affectedLeaseDecisions"] == sorted(
        expected, key=lambda item: item["leaseId"]
    )


def test_any_current_snapshot_authority_path_marks_all_leases_stale(
    recovery_factory
):
    first, second = _two_disjoint_leases(recovery_factory)
    Path(first["laneRoot"], "recovery-authority-public.pem").write_text(
        "changed authority evidence\n", encoding="utf-8"
    )

    result, _ = _observe(
        recovery_factory, first, ["recovery-authority-public.pem"]
    )

    assert result["affectedLeaseDecisions"] == sorted(
        [
            {
                "leaseId": lease["leaseId"],
                "decision": "STALE",
                "reason": "AUTHORITY_AFFECTED",
            }
            for lease in (first, second)
        ],
        key=lambda item: item["leaseId"],
    )


def test_task5_quarantines_preexisting_breach_before_unlock_and_raise(
    recovery_factory
):
    lease = _advance(recovery_factory, _acquire(recovery_factory), "ACTIVE")
    Path(lease["laneRoot"], "services/neutral-a").mkdir(parents=True)
    Path(lease["laneRoot"], "build").mkdir()
    _untracked_breach(lease)

    with pytest.raises(ControlledCoordinationError) as caught:
        guard.run_guarded_command(
            lease,
            Path(lease["laneRoot"]),
            [sys.executable, str(WRITER), "write", str(Path(lease["laneRoot"]) / "services/neutral-a/ok.txt")],
            cwd=Path(lease["laneRoot"]),
            environment={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"},
        )
    assert caught.value.code == "WRITESET_BREACH"
    assert caught.value.observedPaths == ["breach.txt", "build"]
    journal = _journal(recovery_factory)
    assert journal["recoveryState"] == "PROJECT_WRITESET_RECOVERY"
    assert journal["receipts"][-1]["receiptType"] == "WRITE_OBSERVATION"


def test_task5_quarantine_receipt_only_claims_absent_ephemeral_paths(
    recovery_factory,
):
    lease = _advance(recovery_factory, _acquire(recovery_factory), "ACTIVE")
    Path(lease["laneRoot"], "services/neutral-a").mkdir(parents=True)
    remaining = Path(lease["laneRoot"], "build/neutral-a")
    remaining.mkdir(parents=True)
    _untracked_breach(lease)

    with pytest.raises(ControlledCoordinationError) as caught:
        guard.run_guarded_command(
            lease,
            Path(lease["laneRoot"]),
            [
                sys.executable,
                str(WRITER),
                "write",
                str(Path(lease["laneRoot"]) / "services/neutral-a/ok.txt"),
            ],
            cwd=Path(lease["laneRoot"]),
            environment={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )

    assert caught.value.code == "WRITESET_BREACH"
    journal = _journal(recovery_factory)
    command = journal["receipts"][-1]["evidence"]["command"]
    assert command["ephemeralPathsRemoved"] == []
    assert remaining.is_dir()


def test_recovery_waits_for_task5_remaining_ephemeral_cleanup(recovery_factory):
    lease = _advance(recovery_factory, _acquire(recovery_factory), "ACTIVE")
    Path(lease["laneRoot"], "services/neutral-a").mkdir(parents=True)
    remaining = Path(lease["laneRoot"], "build/neutral-a")
    remaining.mkdir(parents=True)
    _untracked_breach(lease)

    with pytest.raises(ControlledCoordinationError) as breach:
        guard.run_guarded_command(
            lease,
            Path(lease["laneRoot"]),
            [
                sys.executable,
                str(WRITER),
                "write",
                str(Path(lease["laneRoot"]) / "services/neutral-a/ok.txt"),
            ],
            cwd=Path(lease["laneRoot"]),
            environment={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
    assert breach.value.code == "WRITESET_BREACH"

    command = _recovery_command(recovery_factory)
    with pytest.raises(ControlledCoordinationError) as blocked:
        record_project_recovery(
            recovery_factory.repository_root,
            recovery_factory.source_root,
            command,
        )
    assert blocked.value.code == "EPHEMERAL_PATH_NOT_REMOVED"
    assert _journal(recovery_factory)["recoveryState"] == "PROJECT_WRITESET_RECOVERY"

    remaining.rmdir()
    result = record_project_recovery(
        recovery_factory.repository_root,
        recovery_factory.source_root,
        command,
    )
    assert result["recoveryState"] == "CLEAR"


def test_task5_after_breach_receipt_binds_the_actual_before_inventory(
    tmp_path, monkeypatch, coordinator_state_factory
):
    monkeypatch.setenv(
        "AGENT_EVOLUTION_COORDINATOR_ROOT", str(tmp_path / "coordinator-state")
    )
    lane = tmp_path / "guarded-lane"
    source = tmp_path / "source"
    lane.mkdir()
    source.mkdir()
    _git(lane, "init", "-q")
    _git(lane, "config", "user.name", "Recovery Guard Test")
    _git(lane, "config", "user.email", "recovery-guard@example.test")
    (lane / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(lane, "add", ".")
    _git(lane, "commit", "-qm", "base")
    lease = _persist_active_lease(
        coordinator_state_factory, lane, source, ["allowed.txt"], []
    )
    expected_before = {
        "paths": [],
        "trackedPaths": [],
        "untrackedPaths": [],
        "ignoredPaths": [],
        "symlinkPaths": [],
        "entries": [],
    }

    def escape(argv, *, cwd, environment, profile):
        del argv, environment, profile
        Path(cwd, "breach.txt").write_text("escaped\n", encoding="utf-8")
        return subprocess.CompletedProcess(["writer"], 0, b"", b"")

    monkeypatch.setattr(guard, "_validate_sandbox_exec", lambda: None)
    monkeypatch.setattr(guard, "_run_sandboxed", escape)
    with pytest.raises(ControlledCoordinationError) as caught:
        guard.run_guarded_command(
            lease,
            lane,
            ["writer"],
            cwd=lane,
            environment={"PATH": "/usr/bin:/bin"},
        )
    assert caught.value.code == "WRITESET_BREACH"
    with CoordinatorStateStore.open(lease) as store:
        journal = store.read_journal()
    assert journal is not None
    command = journal["receipts"][-1]["evidence"]["command"]
    assert command["beforeInventoryDigest"] == _sha256(expected_before)


def test_project_quarantine_revokes_all_leases_and_blocks_all_mutation_boundaries(
    recovery_factory
):
    first, second = _two_disjoint_leases(recovery_factory)
    first = _advance(recovery_factory, first, "ACTIVE")
    breach = _untracked_breach(first)
    transition = _transition_command(recovery_factory, second, "ACTIVE")
    result, _ = _observe(recovery_factory, first, [breach])

    assert set(result["revokedLeaseIds"]) == {first["leaseId"], second["leaseId"]}
    journal = _journal(recovery_factory)
    assert all(
        lease["recoveryStatus"] == "PROJECT_WRITESET_RECOVERY"
        for lease in journal["leases"]
    )
    assert journal["nextFencingToken"] > max(
        lease["fencingToken"] for lease in journal["leases"]
    )

    third = recovery_factory.acquire(
        slice_id="slice:neutral-c",
        attempt_id="attempt:neutral-c",
        owner="owner:neutral-c",
        exact_write_set="services/neutral-c",
    )
    with pytest.raises(ControlledCoordinationError) as acquire_error:
        coordinator.acquire_lane_lease(
            recovery_factory.repository_root, recovery_factory.source_root, third
        )
    assert acquire_error.value.code == "COORDINATOR_RECOVERY_REQUIRED"

    with pytest.raises(ControlledCoordinationError) as transition_error:
        coordinator.transition_lane_lease(
            recovery_factory.repository_root,
            recovery_factory.source_root,
            transition,
        )
    assert transition_error.value.code == "COORDINATOR_RECOVERY_REQUIRED"

    with pytest.raises(ControlledCoordinationError) as guard_error:
        guard.run_guarded_command(
            first,
            Path(first["laneRoot"]),
            [sys.executable, str(WRITER), "write", str(Path(first["laneRoot"]) / "services/neutral-a/again.txt")],
            cwd=Path(first["laneRoot"]),
            environment={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"},
        )
    assert guard_error.value.code == "COORDINATOR_RECOVERY_REQUIRED"


def test_observation_replay_is_exact_and_widened_breach_unions_paths(
    recovery_factory
):
    lease = _acquire(recovery_factory)
    first_path = _untracked_breach(lease, "first.txt")
    first, command = _observe(recovery_factory, lease, [first_path])
    version = _journal(recovery_factory)["journalVersion"]

    replay = observe_lane_writes(
        recovery_factory.repository_root, recovery_factory.source_root, command
    )
    assert replay == first
    assert _journal(recovery_factory)["journalVersion"] == version

    conflicting = _observation_command(
        lease, [first_path], observed_at="2026-08-13T13:00:15Z"
    )
    with pytest.raises(ControlledCoordinationError) as conflict:
        observe_lane_writes(
            recovery_factory.repository_root,
            recovery_factory.source_root,
            conflicting,
        )
    assert conflict.value.code == "WRITE_OBSERVATION_IDEMPOTENCY_CONFLICT"

    second_path = _untracked_breach(lease, "second.txt")
    widened, _ = _observe(
        recovery_factory,
        lease,
        [first_path, second_path],
        observed_at="2026-08-13T13:00:30Z",
    )
    assert widened["observedWriteSet"] == [first_path, second_path]


def test_concurrent_breach_and_acquire_cannot_leave_admitted_unrevoked_lane(
    recovery_factory
):
    first = _acquire(recovery_factory)
    breach = _untracked_breach(first)
    observation = _observation_command(first, [breach])
    third = recovery_factory.acquire(
        slice_id="slice:neutral-c",
        attempt_id="attempt:neutral-c",
        owner="owner:neutral-c",
        exact_write_set="services/neutral-c",
    )

    def observe():
        for _ in range(20):
            try:
                return observe_lane_writes(
                    recovery_factory.repository_root,
                    recovery_factory.source_root,
                    observation,
                )
            except ControlledCoordinationError as exc:
                if exc.code != "COORDINATOR_LOCK_BUSY":
                    return exc.code
        return "COORDINATOR_LOCK_BUSY"

    def acquire():
        try:
            return coordinator.acquire_lane_lease(
                recovery_factory.repository_root,
                recovery_factory.source_root,
                third,
            )
        except ControlledCoordinationError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        observed_result, acquired_result = list(pool.map(lambda fn: fn(), [observe, acquire]))

    journal = _journal(recovery_factory)
    assert journal["recoveryState"] == "PROJECT_WRITESET_RECOVERY"
    admitted_third = [
        lease for lease in journal["leases"] if lease["sliceId"] == "slice:neutral-c"
    ]
    assert not admitted_third or admitted_third[0]["recoveryStatus"] == "PROJECT_WRITESET_RECOVERY"
    assert isinstance(observed_result, dict) or observed_result == "COORDINATOR_LOCK_BUSY"
    assert isinstance(acquired_result, dict) or acquired_result in {
        "COORDINATOR_LOCK_BUSY",
        "COORDINATOR_RECOVERY_REQUIRED",
    }


def test_concurrent_breaches_serialize_without_losing_paths_or_tokens(
    recovery_factory
):
    first, second = _two_disjoint_leases(recovery_factory)
    first_path = _untracked_breach(first, "first-lane.txt")
    second_path = _untracked_breach(second, "second-lane.txt")
    commands = [
        _observation_command(first, [first_path]),
        _observation_command(second, [second_path]),
    ]

    def run(command):
        for _ in range(20):
            try:
                return observe_lane_writes(
                    recovery_factory.repository_root,
                    recovery_factory.source_root,
                    command,
                )
            except ControlledCoordinationError as exc:
                if exc.code != "COORDINATOR_LOCK_BUSY":
                    raise
        raise AssertionError("observation never acquired the project lock")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, commands))

    journal = _journal(recovery_factory)
    assert journal["recoveryEvidence"]["observedWriteSet"] == sorted(
        [first_path, second_path]
    )
    assert journal["nextFencingToken"] > max(
        lease["fencingToken"] for lease in journal["leases"]
    )


def test_signed_recovery_is_current_exact_and_idempotent(recovery_factory):
    first, second = _two_disjoint_leases(recovery_factory)
    breach = _untracked_breach(first)
    _observe(recovery_factory, first, [breach])
    command = _recovery_command(recovery_factory)

    result = record_project_recovery(
        recovery_factory.repository_root, recovery_factory.source_root, command
    )
    version = _journal(recovery_factory)["journalVersion"]
    replay = record_project_recovery(
        recovery_factory.repository_root, recovery_factory.source_root, command
    )

    assert result == replay
    assert _journal(recovery_factory)["journalVersion"] == version
    assert result["recoveryState"] == "CLEAR"
    assert set(result["releasedLeaseIds"]) == {first["leaseId"], second["leaseId"]}
    journal = _journal(recovery_factory)
    assert all(lease["released"] for lease in journal["leases"])
    assert all(lease["recoveryStatus"] == "CLEAR" for lease in journal["leases"])


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("version", "RECOVERY_JOURNAL_VERSION_MISMATCH"),
        ("writeset", "RECOVERY_WRITESET_MISMATCH"),
        ("decisions", "RECOVERY_DECISION_SET_MISMATCH"),
        ("proofs", "RECOVERY_LEASE_SET_MISMATCH"),
        ("replacement", "COORDINATOR_COMMAND_INVALID"),
    ],
)
def test_recovery_requires_exact_version_writeset_decisions_and_proofs(
    recovery_factory, mutation, code
):
    lease = _acquire(recovery_factory)
    breach = _untracked_breach(lease)
    _observe(recovery_factory, lease, [breach])
    command = _recovery_command(recovery_factory)
    if mutation == "version":
        command["expectedJournalVersion"] -= 1
    elif mutation == "writeset":
        command["observedWriteSet"].append("forged.txt")
    elif mutation == "decisions":
        command["affectedLeaseDecisions"][0]["reason"] = "WRITESET_OVERLAP"
    elif mutation == "proofs":
        command["processQuiescenceProofs"] = []
    else:
        command["replacementPlanRequired"] = False
    command["signature"] = _sign(
        recovery_factory.recovery_private_key,
        _recovery_signature_payload(command),
        _RECOVERY_NAMESPACE,
    )
    _command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        record_project_recovery(
            recovery_factory.repository_root, recovery_factory.source_root, command
        )
    assert caught.value.code == code


def test_recovery_rejects_wrong_or_changed_authority_and_fake_path(
    recovery_factory, monkeypatch, tmp_path
):
    lease = _acquire(recovery_factory)
    breach = _untracked_breach(lease)
    _observe(recovery_factory, lease, [breach])

    wrong = _recovery_command(
        recovery_factory, private_key=recovery_factory.wrong_recovery_private_key
    )
    fake = tmp_path / "fake-bin"
    fake.mkdir()
    (fake / "ssh-keygen").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(fake / "ssh-keygen", 0o755)
    monkeypatch.setenv("PATH", str(fake))
    with pytest.raises(ControlledCoordinationError) as wrong_error:
        record_project_recovery(
            recovery_factory.repository_root, recovery_factory.source_root, wrong
        )
    assert wrong_error.value.code == "RECOVERY_SIGNATURE_INVALID"

    current = _recovery_command(recovery_factory)
    Path(recovery_factory.source_root, "recovery-authority-public.pem").write_text(
        _public_key(recovery_factory.wrong_recovery_private_key), encoding="utf-8"
    )
    with pytest.raises(ControlledCoordinationError) as changed_error:
        record_project_recovery(
            recovery_factory.repository_root, recovery_factory.source_root, current
        )
    assert changed_error.value.code in {
        "RECOVERY_AUTHORITY_NOT_CURRENT",
        "LIVE_AUTHORITY_SNAPSHOT_INVALID",
    }


def test_recovery_rejects_unrelated_live_authority_snapshot_drift(recovery_factory):
    lease = _acquire(recovery_factory)
    breach = _untracked_breach(lease)
    _observe(recovery_factory, lease, [breach])
    command = _recovery_command(recovery_factory)
    decisions = Path(recovery_factory.source_root, "decisions.md")
    decisions.write_text(
        decisions.read_text(encoding="utf-8") + "\nUnrelatedChange = YES\n",
        encoding="utf-8",
    )

    with pytest.raises(ControlledCoordinationError) as caught:
        record_project_recovery(
            recovery_factory.repository_root, recovery_factory.source_root, command
        )
    assert caught.value.code == "RECOVERY_AUTHORITY_SNAPSHOT_CHANGED"


def test_recovery_rejects_lane_identity_drift_and_releases_retained_cancelled(
    recovery_factory
):
    cancelled, breached = _two_disjoint_leases(recovery_factory)
    cancelled = coordinator.transition_lane_lease(
        recovery_factory.repository_root,
        recovery_factory.source_root,
        _transition_command(recovery_factory, cancelled, "CANCELLED"),
    )
    assert cancelled["released"] is False
    breach = _untracked_breach(breached)
    _observe(recovery_factory, breached, [breach])
    command = _recovery_command(recovery_factory)

    lane = Path(breached["laneRoot"])
    moved = lane.with_name(lane.name + "-old")
    lane.rename(moved)
    lane.mkdir()
    with pytest.raises(ControlledCoordinationError) as drift:
        record_project_recovery(
            recovery_factory.repository_root, recovery_factory.source_root, command
        )
    assert drift.value.code == "LANE_ROOT_IDENTITY_CHANGED"

    lane.rmdir()
    moved.rename(lane)
    result = record_project_recovery(
        recovery_factory.repository_root, recovery_factory.source_root, command
    )
    assert cancelled["leaseId"] in result["releasedLeaseIds"]


def test_recovery_rejects_old_plan_attempt_and_allows_only_fresh_plan(
    recovery_factory
):
    lease = _acquire(recovery_factory)
    breach = _untracked_breach(lease)
    _observe(recovery_factory, lease, [breach])
    recovery = _recovery_command(recovery_factory)
    record_project_recovery(
        recovery_factory.repository_root, recovery_factory.source_root, recovery
    )

    old = recovery_factory.acquire(create_lane=False)
    old["laneRoot"] = lease["laneRoot"]
    with pytest.raises(ControlledCoordinationError) as old_error:
        coordinator.acquire_lane_lease(
            recovery_factory.repository_root, recovery_factory.source_root, old
        )
    assert old_error.value.code in {
        "TERMINAL_ACQUISITION_REPLAY",
        "RECOVERED_PLAN_IDENTITY_REUSED",
    }

    fresh = _acquire(
        recovery_factory,
        attempt_id="attempt:neutral-c",
        lane_name="slice-neutral-c",
        as_of="2026-08-13T12:05:00Z",
    )
    assert fresh["attemptId"] == "attempt:neutral-c"
    assert fresh["fencingToken"] >= _journal(recovery_factory)["nextFencingToken"] - 1


@pytest.mark.parametrize("reuse", ["batch", "attempt"])
def test_recovery_permanently_retires_batch_and_attempt_independently(
    recovery_factory, reuse
):
    retired = _acquire(recovery_factory)
    breach = _untracked_breach(retired)
    _observe(recovery_factory, retired, [breach])
    record_project_recovery(
        recovery_factory.repository_root,
        recovery_factory.source_root,
        _recovery_command(recovery_factory),
    )
    if reuse == "batch":
        command = recovery_factory.acquire(
            attempt_id="attempt:neutral-b",
            lane_name="slice-neutral-b",
        )
        assert command["batchPlanId"] == retired["batchPlanId"]
        assert command["attemptId"] != retired["attemptId"]
    else:
        command = recovery_factory.acquire(
            lane_name="slice-neutral-c",
            as_of="2026-08-13T12:05:00Z",
        )
        assert command["batchPlanId"] != retired["batchPlanId"]
        assert command["attemptId"] == retired["attemptId"]

    with pytest.raises(ControlledCoordinationError) as caught:
        coordinator.acquire_lane_lease(
            recovery_factory.repository_root,
            recovery_factory.source_root,
            command,
        )
    assert caught.value.code == "RECOVERED_PLAN_IDENTITY_REUSED"


def test_second_breach_after_fresh_lease_uses_an_independent_recovery_cycle(
    recovery_factory
):
    first = _acquire(recovery_factory)
    first_path = _untracked_breach(first, "first-cycle.txt")
    _observe(recovery_factory, first, [first_path])
    record_project_recovery(
        recovery_factory.repository_root,
        recovery_factory.source_root,
        _recovery_command(recovery_factory, recovery_id="recovery:" + "1" * 24),
    )
    fresh = _acquire(
        recovery_factory,
        attempt_id="attempt:neutral-c",
        lane_name="slice-neutral-c",
        as_of="2026-08-13T12:05:00Z",
    )
    second_path = _untracked_breach(fresh, "second-cycle.txt")

    second, _ = _observe(recovery_factory, fresh, [second_path])

    assert second["observedWriteSet"] == [second_path]
    assert second["revokedLeaseIds"] == [fresh["leaseId"]]
    result = record_project_recovery(
        recovery_factory.repository_root,
        recovery_factory.source_root,
        _recovery_command(recovery_factory, recovery_id="recovery:" + "2" * 24),
    )
    assert result["releasedLeaseIds"] == [fresh["leaseId"]]


def _journal_path() -> Path:
    root = Path(os.environ["AGENT_EVOLUTION_COORDINATOR_ROOT"])
    paths = list(root.glob("*.journal.json"))
    assert len(paths) == 1
    return paths[0]


def _rewrite_journal(mutator) -> None:
    path = _journal_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutator(payload)
    payload["receipts"][-1]["journalDigest"] = "sha256:" + "0" * 64
    payload["receipts"][-1]["journalDigest"] = _sha256(payload)
    path.write_bytes(canonical_json_bytes(payload) + b"\n")


@pytest.mark.parametrize(
    "mutation",
    [
        "delete-observation",
        "duplicate-recovery",
        "reorder",
        "rewrite-decision",
        "rewrite-authority-snapshot",
        "rewrite-recorded-at",
        "token-rollback",
    ],
)
def test_store_rejects_recovery_receipt_evidence_and_token_rewrites(
    recovery_factory, mutation
):
    lease = _acquire(recovery_factory)
    breach = _untracked_breach(lease)
    _observe(recovery_factory, lease, [breach])
    command = _recovery_command(recovery_factory)
    record_project_recovery(
        recovery_factory.repository_root, recovery_factory.source_root, command
    )

    def mutate(journal):
        if mutation == "delete-observation":
            del journal["receipts"][-2]
            journal["journalVersion"] -= 1
            for index, receipt in enumerate(journal["receipts"], start=1):
                receipt["previousJournalVersion"] = index - 1
                receipt["nextJournalVersion"] = index
        elif mutation == "duplicate-recovery":
            journal["receipts"][-2] = copy.deepcopy(journal["receipts"][-1])
            journal["receipts"][-2]["previousJournalVersion"] -= 1
            journal["receipts"][-2]["nextJournalVersion"] -= 1
        elif mutation == "reorder":
            journal["receipts"][-2:] = reversed(journal["receipts"][-2:])
            for index, receipt in enumerate(journal["receipts"], start=1):
                receipt["previousJournalVersion"] = index - 1
                receipt["nextJournalVersion"] = index
        elif mutation == "rewrite-decision":
            journal["recoveryEvidence"]["affectedLeaseDecisions"][0]["reason"] = "WRITESET_OVERLAP"
            journal["receipts"][-2]["evidence"]["affectedLeaseDecisions"][0]["reason"] = "WRITESET_OVERLAP"
            journal["receipts"][-1]["evidence"]["affectedLeaseDecisions"][0]["reason"] = "WRITESET_OVERLAP"
        elif mutation == "rewrite-authority-snapshot":
            journal["receipts"][-1]["authoritySnapshotFingerprint"] = (
                "sha256:" + "f" * 64
            )
        elif mutation == "rewrite-recorded-at":
            journal["receipts"][-1]["recordedAt"] = "2026-08-13T14:00:00Z"
        else:
            journal["nextFencingToken"] = lease["fencingToken"]

    _rewrite_journal(mutate)
    with pytest.raises(ControlledCoordinationError) as caught:
        _journal(recovery_factory)
    assert caught.value.code == "COORDINATOR_STATE_CORRUPT"


def test_store_rejects_acquire_interleaved_inside_a_recovery_cycle(
    recovery_factory,
):
    first = _acquire(recovery_factory)
    breach = _untracked_breach(first)
    _observe(recovery_factory, first, [breach])
    record_project_recovery(
        recovery_factory.repository_root,
        recovery_factory.source_root,
        _recovery_command(recovery_factory),
    )
    _acquire(
        recovery_factory,
        attempt_id="attempt:neutral-c",
        lane_name="slice-neutral-c",
        as_of="2026-08-13T12:05:00Z",
    )

    def mutate(journal):
        acquire = journal["receipts"].pop()
        journal["receipts"].insert(-1, acquire)
        recovery = journal["receipts"][-1]
        command = recovery["evidence"]["command"]
        command["expectedJournalVersion"] += 1
        command["signature"] = _sign(
            recovery_factory.recovery_private_key,
            _recovery_signature_payload(command),
            _RECOVERY_NAMESPACE,
        )
        _command_digest(command)
        recovery["commandDigest"] = command["commandDigest"]
        journal["recoveryEvidence"]["recoveryCommand"] = copy.deepcopy(command)
        for index, receipt in enumerate(journal["receipts"], start=1):
            receipt["previousJournalVersion"] = index - 1
            receipt["nextJournalVersion"] = index

    _rewrite_journal(mutate)
    with pytest.raises(ControlledCoordinationError) as caught:
        _journal(recovery_factory)
    assert caught.value.code == "COORDINATOR_STATE_CORRUPT"


def test_store_rejects_self_consistent_revoked_lease_omission(recovery_factory):
    first, second = _two_disjoint_leases(recovery_factory)
    breach = _untracked_breach(first)
    _observe(recovery_factory, first, [breach])
    record_project_recovery(
        recovery_factory.repository_root,
        recovery_factory.source_root,
        _recovery_command(recovery_factory),
    )

    def mutate(journal):
        omitted_id = second["leaseId"]
        observation = journal["receipts"][-2]
        recovery = journal["receipts"][-1]
        for container in (
            journal["recoveryEvidence"],
            observation["evidence"],
            recovery["evidence"],
        ):
            container["revokedLeaseIds"] = [
                lease_id
                for lease_id in container["revokedLeaseIds"]
                if lease_id != omitted_id
            ]
            container["affectedLeaseDecisions"] = [
                item
                for item in container["affectedLeaseDecisions"]
                if item["leaseId"] != omitted_id
            ]
        command = recovery["evidence"]["command"]
        command["processQuiescenceProofs"] = [
            proof
            for proof in command["processQuiescenceProofs"]
            if proof["leaseId"] != omitted_id
        ]
        command["affectedLeaseDecisions"] = [
            item
            for item in command["affectedLeaseDecisions"]
            if item["leaseId"] != omitted_id
        ]
        command["signature"] = _sign(
            recovery_factory.recovery_private_key,
            _recovery_signature_payload(command),
            _RECOVERY_NAMESPACE,
        )
        _command_digest(command)
        recovery["commandDigest"] = command["commandDigest"]
        recovery["fencingToken"] = first["fencingToken"]
        journal["recoveryEvidence"]["recoveryCommand"] = copy.deepcopy(command)
        omitted = next(
            lease for lease in journal["leases"] if lease["leaseId"] == omitted_id
        )
        omitted["state"] = "ADMITTED"
        omitted["released"] = False
        omitted["recoveryStatus"] = "CLEAR"
        omitted["lastTransitionAt"] = omitted["acquiredAt"]

    _rewrite_journal(mutate)
    with pytest.raises(ControlledCoordinationError) as caught:
        _journal(recovery_factory)
    assert caught.value.code == "COORDINATOR_STATE_CORRUPT"


@pytest.mark.parametrize(
    "mutation", ["authority", "recovery-id", "proof-time", "signature"]
)
def test_store_rejects_self_consistent_recovery_sshsig_rewrites(
    recovery_factory, mutation
):
    lease = _acquire(recovery_factory)
    breach = _untracked_breach(lease)
    _observe(recovery_factory, lease, [breach])
    record_project_recovery(
        recovery_factory.repository_root,
        recovery_factory.source_root,
        _recovery_command(recovery_factory),
    )

    def mutate(journal):
        receipt = journal["receipts"][-1]
        command = receipt["evidence"]["command"]
        if mutation == "authority":
            command["recoveryAuthorityReference"] = "wrong-recovery-public.pem"
            command["recoveryAuthorityDigest"] = "sha256:" + "d" * 64
        elif mutation == "recovery-id":
            command["recoveryId"] = "recovery:" + "b" * 24
        elif mutation == "proof-time":
            for proof in command["processQuiescenceProofs"]:
                proof["observedAt"] = "2026-08-13T14:00:00Z"
            receipt["recordedAt"] = "2026-08-13T14:00:00Z"
            for item in journal["leases"]:
                if item["leaseId"] in receipt["evidence"]["revokedLeaseIds"]:
                    item["lastTransitionAt"] = "2026-08-13T14:00:00Z"
        else:
            command["signature"] += "tampered"
        _command_digest(command)
        receipt["commandDigest"] = command["commandDigest"]
        receipt["receiptId"] = _receipt_id(receipt)
        journal["recoveryEvidence"]["recoveryCommand"] = copy.deepcopy(command)

    _rewrite_journal(mutate)
    with pytest.raises(ControlledCoordinationError) as caught:
        _journal(recovery_factory)
    assert caught.value.code == "COORDINATOR_STATE_CORRUPT"


def test_recovery_crash_before_replace_is_retryable_without_partial_release(
    recovery_factory, monkeypatch
):
    lease = _acquire(recovery_factory)
    breach = _untracked_breach(lease)
    _observe(recovery_factory, lease, [breach])
    command = _recovery_command(recovery_factory)
    original = CoordinatorStateStore.replace_journal
    failed = False

    def fail_once(self, expected_version, journal, receipt):
        nonlocal failed
        if receipt["receiptType"] == "RECOVERY" and not failed:
            failed = True
            raise ControlledCoordinationError(
                "COORDINATOR_STATE_WRITE_FAILED", "injected recovery crash"
            )
        return original(self, expected_version, journal, receipt)

    monkeypatch.setattr(CoordinatorStateStore, "replace_journal", fail_once)
    with pytest.raises(ControlledCoordinationError) as crashed:
        record_project_recovery(
            recovery_factory.repository_root, recovery_factory.source_root, command
        )
    assert crashed.value.code == "COORDINATOR_STATE_WRITE_FAILED"
    pending = _journal(recovery_factory)
    assert pending["recoveryState"] == "PROJECT_WRITESET_RECOVERY"
    assert all(not item["released"] for item in pending["leases"])

    result = record_project_recovery(
        recovery_factory.repository_root, recovery_factory.source_root, command
    )
    assert result["recoveryState"] == "CLEAR"


def test_recovery_fails_closed_on_journal_loss_or_corruption(
    recovery_factory
):
    lease = _acquire(recovery_factory)
    breach = _untracked_breach(lease)
    _observe(recovery_factory, lease, [breach])
    command = _recovery_command(recovery_factory)
    path = _journal_path()
    original = path.read_bytes()

    path.write_text("{truncated", encoding="utf-8")
    with pytest.raises(ControlledCoordinationError) as corrupt:
        record_project_recovery(
            recovery_factory.repository_root, recovery_factory.source_root, command
        )
    assert corrupt.value.code == "COORDINATOR_JOURNAL_INVALID"

    path.write_bytes(original)
    path.unlink()
    with pytest.raises(ControlledCoordinationError) as lost:
        record_project_recovery(
            recovery_factory.repository_root, recovery_factory.source_root, command
        )
    assert lost.value.code == "COORDINATOR_JOURNAL_MISSING"
