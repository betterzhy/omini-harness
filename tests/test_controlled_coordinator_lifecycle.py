from __future__ import annotations

import copy
import subprocess
import sys

import pytest

from evolution_harness import controlled_coordinator as coordinator
from evolution_harness.authority import build_authority_snapshot
from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError
from evolution_harness.hashing import canonical_json_bytes, sha256_bytes
from test_controlled_coordinator_acquire import AcquisitionFactory, _committed_source


_CANDIDATE = {
    "commit": "4" * 40,
    "parent": "5" * 40,
    "tree": "6" * 40,
}


def _sha256(value):
    return "sha256:" + sha256_bytes(canonical_json_bytes(value))


def _command_digest(command):
    command["commandDigest"] = _sha256(
        {key: value for key, value in command.items() if key != "commandDigest"}
    )
    return command


@pytest.fixture
def lifecycle_factory(tmp_path, monkeypatch, repository_root, controlled_factory):
    monkeypatch.setenv(
        "AGENT_EVOLUTION_COORDINATOR_ROOT", str(tmp_path / "coordinator-state")
    )
    source = _committed_source(
        repository_root, tmp_path / "external-project", controlled_factory
    )
    return AcquisitionFactory(repository_root, source, controlled_factory)


def _current_authorities(factory):
    snapshot = build_authority_snapshot(
        factory.repository_root,
        factory.repository_root / "integrations/neutral-shadow",
        factory.source_root,
    )
    return snapshot, {item["id"]: item for item in snapshot["authorities"]}


def _transition_command(
    factory,
    lease,
    next_state,
    *,
    expected_state=None,
    fencing_token=None,
    candidate_identity=None,
):
    snapshot, authorities = _current_authorities(factory)
    lifecycle_authority = authorities["global-status"]
    reviewer_authority = authorities["coordinator-issuer"]
    expected = expected_state or lease["state"]
    if candidate_identity is None:
        if next_state == "FIXED_CANDIDATE":
            candidate_identity = copy.deepcopy(_CANDIDATE)
        else:
            candidate_identity = copy.deepcopy(lease["candidateIdentity"])

    review = None
    if next_state == "REVIEW_GO":
        review = {
            "candidateIdentity": copy.deepcopy(candidate_identity),
            "reviewerId": reviewer_authority["id"],
            "reviewerAuthorityReference": reviewer_authority["path"],
            "reviewerAuthorityDigest": "sha256:" + reviewer_authority["sha256"],
            "verdict": "GO_ZERO_FINDINGS",
            "findingCounts": {"p0": 0, "p1": 0, "p2": 0},
            "reviewedAt": "2026-08-13T12:29:30Z",
        }
        review["reviewBindingDigest"] = _sha256(
            {
                "candidateIdentity": candidate_identity,
                "authoritySnapshotFingerprint": snapshot["snapshotFingerprint"],
                "attemptId": lease["attemptId"],
                "reviewerId": review["reviewerId"],
                "reviewerAuthorityReference": review["reviewerAuthorityReference"],
                "reviewerAuthorityDigest": review["reviewerAuthorityDigest"],
            }
        )
        review["evidenceDigest"] = _sha256(review)

    proof = {
        "authorityReference": lifecycle_authority["path"],
        "authorityDigest": "sha256:" + lifecycle_authority["sha256"],
        "attemptId": lease["attemptId"],
        "expectedState": expected,
        "nextState": next_state,
        "candidateIdentity": copy.deepcopy(candidate_identity),
        "reviewBindingDigest": (
            None if review is None else review["reviewBindingDigest"]
        ),
        "reviewEvidenceDigest": (
            None if review is None else review["evidenceDigest"]
        ),
        "reviewerId": None if review is None else review["reviewerId"],
        "reviewerAuthorityReference": (
            None if review is None else review["reviewerAuthorityReference"]
        ),
        "reviewerAuthorityDigest": (
            None if review is None else review["reviewerAuthorityDigest"]
        ),
        "assertedAt": "2026-08-13T12:29:00Z",
    }
    proof["proofDigest"] = _sha256(proof)
    return _command_digest(
        {
            "schemaVersion": "controlled-coordinator-transition-command/v1",
            "projectExecutionKey": lease["projectExecutionKey"],
            "leaseId": lease["leaseId"],
            "attemptId": lease["attemptId"],
            "fencingToken": (
                lease["fencingToken"] if fencing_token is None else fencing_token
            ),
            "expectedState": expected,
            "nextState": next_state,
            "authoritySnapshotFingerprint": snapshot["snapshotFingerprint"],
            "candidateIdentity": copy.deepcopy(candidate_identity),
            "processQuiescence": {
                "status": "QUIESCENT",
                "observedAt": "2026-08-13T12:30:00Z",
                "processIds": [],
            },
            "lifecycleAuthorityProof": proof,
            "reviewEvidence": review,
        }
    )


def _rebind_transition(command):
    review = command["reviewEvidence"]
    if review is not None:
        review["candidateIdentity"] = copy.deepcopy(command["candidateIdentity"])
        review["reviewBindingDigest"] = _sha256(
            {
                "candidateIdentity": command["candidateIdentity"],
                "authoritySnapshotFingerprint": command[
                    "authoritySnapshotFingerprint"
                ],
                "attemptId": command["attemptId"],
                "reviewerId": review["reviewerId"],
                "reviewerAuthorityReference": review[
                    "reviewerAuthorityReference"
                ],
                "reviewerAuthorityDigest": review["reviewerAuthorityDigest"],
            }
        )
        review["evidenceDigest"] = _sha256(
            {key: value for key, value in review.items() if key != "evidenceDigest"}
        )
    proof = command["lifecycleAuthorityProof"]
    proof.update(
        {
            "attemptId": command["attemptId"],
            "expectedState": command["expectedState"],
            "nextState": command["nextState"],
            "candidateIdentity": copy.deepcopy(command["candidateIdentity"]),
            "reviewBindingDigest": (
                None if review is None else review["reviewBindingDigest"]
            ),
            "reviewEvidenceDigest": (
                None if review is None else review["evidenceDigest"]
            ),
            "reviewerId": None if review is None else review["reviewerId"],
            "reviewerAuthorityReference": (
                None if review is None else review["reviewerAuthorityReference"]
            ),
            "reviewerAuthorityDigest": (
                None if review is None else review["reviewerAuthorityDigest"]
            ),
        }
    )
    proof["proofDigest"] = _sha256(
        {key: value for key, value in proof.items() if key != "proofDigest"}
    )
    return _command_digest(command)


def _acquire(factory):
    return coordinator.acquire_lane_lease(
        factory.repository_root,
        factory.source_root,
        factory.acquire(),
    )


def _transition(factory, command):
    return coordinator.transition_lane_lease(
        factory.repository_root,
        factory.source_root,
        command,
    )


def _advance(factory, lease, *states):
    current = lease
    for state in states:
        current = _transition(
            factory, _transition_command(factory, current, state)
        )
    return current


def test_all_allowed_normal_edges_retain_until_closed(lifecycle_factory):
    lease = _acquire(lifecycle_factory)
    original_token = lease["fencingToken"]
    edges = [
        ("ADMITTED", "ACTIVE"),
        ("ACTIVE", "FIXED_CANDIDATE"),
        ("FIXED_CANDIDATE", "REVIEW_GO"),
        ("REVIEW_GO", "QUEUED_FOR_INTEGRATION"),
        ("QUEUED_FOR_INTEGRATION", "INTEGRATING"),
        ("INTEGRATING", "CLOSED"),
    ]

    for expected, next_state in edges:
        command = _transition_command(lifecycle_factory, lease, next_state)
        result = _transition(lifecycle_factory, command)
        assert result["state"] == next_state
        assert result["fencingToken"] == original_token
        assert result["leaseRetained"] is (next_state != "CLOSED")
        assert result["released"] is (next_state == "CLOSED")
        if next_state == "FIXED_CANDIDATE":
            assert result["candidateIdentity"] == _CANDIDATE
        if next_state == "INTEGRATING":
            assert result["leaseRetained"] is True
        lease = result

    journal = lifecycle_factory.journal()
    assert [(item["previousState"], item["nextState"]) for item in journal["receipts"][1:]] == edges
    assert journal["journalVersion"] == 1 + len(edges)
    next_lease = coordinator.acquire_lane_lease(
        lifecycle_factory.repository_root,
        lifecycle_factory.source_root,
        lifecycle_factory.acquire(
            slice_id="slice:neutral-b",
            attempt_id="attempt:neutral-b",
            owner="owner:neutral-b",
            exact_write_set="services/neutral-b",
        ),
    )
    assert next_lease["fencingToken"] > original_token


def test_skipped_state_is_rejected_without_journal_mutation(lifecycle_factory):
    lease = _acquire(lifecycle_factory)
    command = _transition_command(
        lifecycle_factory, lease, "FIXED_CANDIDATE"
    )

    with pytest.raises(ControlledCoordinationError) as caught:
        _transition(lifecycle_factory, command)

    assert caught.value.code == "INVALID_STATE_TRANSITION"
    assert lifecycle_factory.journal()["journalVersion"] == 1


def test_stale_fencing_token_is_rejected_without_journal_mutation(lifecycle_factory):
    lease = _acquire(lifecycle_factory)
    command = _transition_command(
        lifecycle_factory,
        lease,
        "ACTIVE",
        fencing_token=lease["fencingToken"] + 1,
    )

    with pytest.raises(ControlledCoordinationError) as caught:
        _transition(lifecycle_factory, command)

    assert caught.value.code == "STALE_FENCING_TOKEN"
    assert lifecycle_factory.journal()["journalVersion"] == 1


@pytest.mark.parametrize("exceptional", ["BLOCKED", "NO_GO", "STALE"])
def test_exceptional_state_retains_lease(lifecycle_factory, exceptional):
    lease = _acquire(lifecycle_factory)
    result = _transition(
        lifecycle_factory,
        _transition_command(lifecycle_factory, lease, exceptional),
    )

    assert result["leaseRetained"] is True
    assert result["released"] is False
    assert result["state"] == exceptional
    assert result["fencingToken"] == lease["fencingToken"]
    assert lifecycle_factory.journal()["nextFencingToken"] > lease["fencingToken"]


def test_missing_token_and_attempt_mismatch_fail_closed(lifecycle_factory):
    lease = _acquire(lifecycle_factory)
    missing = _transition_command(lifecycle_factory, lease, "ACTIVE")
    del missing["fencingToken"]
    _command_digest(missing)
    with pytest.raises(ControlledCoordinationError) as absent:
        _transition(lifecycle_factory, missing)
    assert absent.value.code == "COORDINATOR_COMMAND_INVALID"

    other_attempt = _transition_command(lifecycle_factory, lease, "ACTIVE")
    other_attempt["attemptId"] = "attempt:other"
    _rebind_transition(other_attempt)
    with pytest.raises(ControlledCoordinationError) as mismatch:
        _transition(lifecycle_factory, other_attempt)
    assert mismatch.value.code == "LEASE_ATTEMPT_MISMATCH"
    assert lifecycle_factory.journal()["journalVersion"] == 1


def test_transition_requires_current_snapshot_and_authority_record(lifecycle_factory):
    lease = _acquire(lifecycle_factory)
    wrong_snapshot = _transition_command(lifecycle_factory, lease, "ACTIVE")
    wrong_snapshot["authoritySnapshotFingerprint"] = "sha256:" + "f" * 64
    _rebind_transition(wrong_snapshot)
    with pytest.raises(ControlledCoordinationError) as fingerprint:
        _transition(lifecycle_factory, wrong_snapshot)
    assert fingerprint.value.code == "LIVE_AUTHORITY_SNAPSHOT_MISMATCH"

    wrong_authority = _transition_command(lifecycle_factory, lease, "ACTIVE")
    wrong_authority["lifecycleAuthorityProof"]["authorityDigest"] = (
        "sha256:" + "e" * 64
    )
    _rebind_transition(wrong_authority)
    with pytest.raises(ControlledCoordinationError) as authority:
        _transition(lifecycle_factory, wrong_authority)
    assert authority.value.code == "LIFECYCLE_AUTHORITY_NOT_CURRENT"
    assert lifecycle_factory.journal()["journalVersion"] == 1


def test_authority_drift_only_allows_explicit_stale_revocation(lifecycle_factory):
    lease = _acquire(lifecycle_factory)
    (lifecycle_factory.source_root / "status.md").write_text(
        "# External Project Status\n\n"
        "ProjectStage = DELIVERY\n"
        "DevelopmentAuthorization = YES_TASK4_DRIFT\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "-C", str(lifecycle_factory.source_root), "add", "status.md"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(lifecycle_factory.source_root),
            "commit",
            "-qm",
            "authority drift",
        ],
        check=True,
    )

    ordinary = _transition_command(lifecycle_factory, lease, "ACTIVE")
    with pytest.raises(ControlledCoordinationError) as drift:
        _transition(lifecycle_factory, ordinary)
    assert drift.value.code == "AUTHORITY_SNAPSHOT_DRIFT"

    stale = _transition_command(lifecycle_factory, lease, "STALE")
    result = _transition(lifecycle_factory, stale)
    journal = lifecycle_factory.journal()
    assert result["state"] == "STALE"
    assert result["leaseRetained"] is True
    assert result["fencingToken"] == lease["fencingToken"]
    assert journal["nextFencingToken"] > lease["fencingToken"]


def test_fixed_candidate_and_review_are_immutable_and_current(lifecycle_factory):
    lease = _advance(lifecycle_factory, _acquire(lifecycle_factory), "ACTIVE")
    fixed = _transition(
        lifecycle_factory,
        _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE"),
    )
    assert fixed["candidateIdentity"] == _CANDIDATE

    changed_candidate = copy.deepcopy(_CANDIDATE)
    changed_candidate["parent"] = "7" * 40
    wrong_candidate = _transition_command(
        lifecycle_factory,
        fixed,
        "REVIEW_GO",
        candidate_identity=changed_candidate,
    )
    with pytest.raises(ControlledCoordinationError) as candidate:
        _transition(lifecycle_factory, wrong_candidate)
    assert candidate.value.code == "CANDIDATE_IDENTITY_MISMATCH"

    wrong_reviewer = _transition_command(lifecycle_factory, fixed, "REVIEW_GO")
    wrong_reviewer["reviewEvidence"]["reviewerId"] = "reviewer:unregistered"
    _rebind_transition(wrong_reviewer)
    with pytest.raises(ControlledCoordinationError) as reviewer:
        _transition(lifecycle_factory, wrong_reviewer)
    assert reviewer.value.code == "REVIEWER_AUTHORITY_NOT_CURRENT"

    review_go = _transition(
        lifecycle_factory,
        _transition_command(lifecycle_factory, fixed, "REVIEW_GO"),
    )
    assert review_go["candidateIdentity"] == _CANDIDATE


def test_cancel_requires_current_authority_and_real_quiescence(lifecycle_factory):
    lease = _acquire(lifecycle_factory)
    missing_authority = _transition_command(lifecycle_factory, lease, "CANCELLED")
    missing_authority["lifecycleAuthorityProof"]["authorityReference"] = (
        "authority/missing.yaml"
    )
    _rebind_transition(missing_authority)
    with pytest.raises(ControlledCoordinationError) as authority:
        _transition(lifecycle_factory, missing_authority)
    assert authority.value.code == "LIFECYCLE_AUTHORITY_NOT_CURRENT"

    live_process = _transition_command(lifecycle_factory, lease, "CANCELLED")
    live_process["processQuiescence"]["processIds"] = [12345]
    _rebind_transition(live_process)
    with pytest.raises(ControlledCoordinationError) as quiescence:
        _transition(lifecycle_factory, live_process)
    assert quiescence.value.code == "PROCESS_NOT_QUIESCENT"

    cancelled_command = _transition_command(lifecycle_factory, lease, "CANCELLED")
    cancelled = _transition(lifecycle_factory, cancelled_command)
    assert cancelled["state"] == "CANCELLED"
    assert cancelled["released"] is True
    assert cancelled["leaseRetained"] is False

    next_lease = coordinator.acquire_lane_lease(
        lifecycle_factory.repository_root,
        lifecycle_factory.source_root,
        lifecycle_factory.acquire(
            slice_id="slice:neutral-b",
            attempt_id="attempt:neutral-b",
            owner="owner:neutral-b",
            exact_write_set="services/neutral-b",
        ),
    )
    assert next_lease["fencingToken"] > lease["fencingToken"]


def test_transition_replay_is_immutable_and_revalidates_live_authority(
    lifecycle_factory,
):
    lease = _acquire(lifecycle_factory)
    command = _transition_command(lifecycle_factory, lease, "ACTIVE")
    first = _transition(lifecycle_factory, command)
    version = lifecycle_factory.journal()["journalVersion"]
    replay = _transition(lifecycle_factory, copy.deepcopy(command))
    assert replay == first
    assert lifecycle_factory.journal()["journalVersion"] == version

    changed = copy.deepcopy(command)
    changed["processQuiescence"]["observedAt"] = "2026-08-13T12:30:01Z"
    _rebind_transition(changed)
    with pytest.raises(ControlledCoordinationError) as conflict:
        _transition(lifecycle_factory, changed)
    assert conflict.value.code == "TRANSITION_IDEMPOTENCY_CONFLICT"

    (lifecycle_factory.source_root / "status.md").write_text(
        "# External Project Status\n\n"
        "ProjectStage = DELIVERY\n"
        "DevelopmentAuthorization = YES_REPLAY_DRIFT\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "-C", str(lifecycle_factory.source_root), "add", "status.md"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(lifecycle_factory.source_root),
            "commit",
            "-qm",
            "replay authority drift",
        ],
        check=True,
    )
    with pytest.raises(ControlledCoordinationError) as replay_drift:
        _transition(lifecycle_factory, copy.deepcopy(command))
    assert replay_drift.value.code == "LIVE_AUTHORITY_SNAPSHOT_MISMATCH"


def test_terminal_is_immutable_and_subprocess_loss_does_not_release(
    lifecycle_factory,
):
    lease = _acquire(lifecycle_factory)
    exited = subprocess.run(
        [sys.executable, "-c", "raise SystemExit(7)"], check=False
    )
    assert exited.returncode == 7
    assert lifecycle_factory.journal()["leases"][0]["released"] is False

    cancelled_command = _transition_command(lifecycle_factory, lease, "CANCELLED")
    cancelled = _transition(lifecycle_factory, cancelled_command)
    assert _transition(lifecycle_factory, copy.deepcopy(cancelled_command)) == cancelled

    after_terminal = _transition_command(
        lifecycle_factory, cancelled, "BLOCKED"
    )
    with pytest.raises(ControlledCoordinationError) as terminal:
        _transition(lifecycle_factory, after_terminal)
    assert terminal.value.code in {
        "INVALID_STATE_TRANSITION",
        "TERMINAL_LEASE_IMMUTABLE",
    }
