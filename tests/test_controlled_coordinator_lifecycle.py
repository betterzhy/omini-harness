from __future__ import annotations

import copy
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from evolution_harness import controlled_coordinator as coordinator
from evolution_harness import controlled_write_guard as write_guard
from evolution_harness.authority import build_authority_snapshot
from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError
from evolution_harness.hashing import canonical_json_bytes, sha256_bytes
from test_controlled_coordinator_acquire import (
    AcquisitionFactory,
    _committed_source,
    _install_ambient_git_view,
    _replace_head_with_worktree_tree,
)


_SSH_KEYGEN = "/usr/bin/ssh-keygen"
_LIFECYCLE_NAMESPACE = "agent-evolution-controlled-lifecycle-v1"
_REVIEW_NAMESPACE = "agent-evolution-controlled-review-v1"


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
    factory = AcquisitionFactory(repository_root, source, controlled_factory)
    for private_name, public_name in (
        ("lifecycle-private.pem", "lifecycle-authority-public.pem"),
        ("reviewer-private.pem", "deep-reviewer-public.pem"),
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
        public_parts = Path(str(private_path) + ".pub").read_text(
            encoding="utf-8"
        ).split()
        (source / public_name).write_text(
            f"{public_parts[0]} {public_parts[1]}\n", encoding="utf-8"
        )
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "add",
            "lifecycle-authority-public.pem",
            "deep-reviewer-public.pem",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "commit", "-qm", "test signing authorities"],
        check=True,
    )
    factory.lifecycle_private_key = tmp_path / "lifecycle-private.pem"
    factory.reviewer_private_key = tmp_path / "reviewer-private.pem"
    return factory


def _current_authorities(factory):
    snapshot = build_authority_snapshot(
        factory.repository_root,
        factory.repository_root / "integrations/neutral-shadow",
        factory.source_root,
    )
    return snapshot, {item["id"]: item for item in snapshot["authorities"]}


def _authority_or_file(factory, authorities, authority_id, reference):
    current = authorities.get(authority_id)
    if current is not None:
        return current
    return {
        "id": authority_id,
        "path": reference,
        "sha256": sha256_bytes((factory.source_root / reference).read_bytes()),
    }


def _sign(private_key, payload, namespace):
    with tempfile.TemporaryDirectory(prefix="task4-signing-payload-") as temporary:
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


def _lifecycle_signature_payload(command):
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


def _review_signature_payload(command, review, required_reviewers, minimum_verdict):
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
        "minimumReviewVerdict": minimum_verdict,
    }


def _acquired_review_policy(factory, lease_or_command):
    lease_id = lease_or_command["leaseId"]
    journal = factory.journal()
    acquire = next(
        receipt["evidence"]["command"]
        for receipt in journal["receipts"]
        if receipt["receiptType"] == "ACQUIRE"
        and any(
            item["leaseId"] == lease_id
            and item["batchPlanId"]
            == receipt["evidence"]["command"]["batchPlanId"]
            and item["sliceId"] == receipt["evidence"]["command"]["sliceId"]
            and item["attemptId"] == receipt["evidence"]["command"]["attemptId"]
            for item in journal["leases"]
        )
    )
    requirements = acquire["executionPlan"]["executionRequirements"]
    assert any(
        item["sliceId"] == acquire["sliceId"]
        for item in requirements["sliceRequirements"]
    )
    return (
        list(requirements["requiredReviewers"]),
        requirements["minimumReviewVerdict"],
    )


def _reviewer_private_key(factory, role):
    return (
        factory.lifecycle_private_key
        if role == "lifecycle-controller"
        else factory.reviewer_private_key
    )


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
    lifecycle_authority = _authority_or_file(
        factory,
        authorities,
        "lifecycle-controller",
        "lifecycle-authority-public.pem",
    )
    expected = expected_state or lease["state"]
    if candidate_identity is None:
        if next_state == "FIXED_CANDIDATE":
            candidate_identity = _create_live_candidate(lease)
        else:
            candidate_identity = copy.deepcopy(lease["candidateIdentity"])

    review_set = []
    if next_state == "REVIEW_GO":
        required_reviewers, minimum_verdict = _acquired_review_policy(factory, lease)
        for role in required_reviewers:
            reviewer_authority = authorities[role]
            review = {
                "candidateIdentity": copy.deepcopy(candidate_identity),
                "reviewerId": reviewer_authority["id"],
                "reviewerRole": role,
                "projectExecutionKey": lease["projectExecutionKey"],
                "leaseId": lease["leaseId"],
                "attemptId": lease["attemptId"],
                "fencingToken": lease["fencingToken"],
                "authoritySnapshotFingerprint": snapshot["snapshotFingerprint"],
                "reviewerAuthorityReference": reviewer_authority["path"],
                "reviewerAuthorityDigest": "sha256:" + reviewer_authority["sha256"],
                "verdict": minimum_verdict,
                "findingCounts": {"p0": 0, "p1": 0, "p2": 0},
                "reviewedAt": "2026-08-13T12:29:30Z",
                "signatureAlgorithm": "ED25519",
                "signatureFormat": "OPENSSH_SSHSIG_V1",
            }
            review["reviewBindingDigest"] = _sha256(
                {
                    "candidateIdentity": candidate_identity,
                    "projectExecutionKey": lease["projectExecutionKey"],
                    "leaseId": lease["leaseId"],
                    "attemptId": lease["attemptId"],
                    "fencingToken": lease["fencingToken"],
                    "authoritySnapshotFingerprint": snapshot["snapshotFingerprint"],
                    "reviewerId": review["reviewerId"],
                    "reviewerRole": review["reviewerRole"],
                    "reviewerAuthorityReference": review["reviewerAuthorityReference"],
                    "reviewerAuthorityDigest": review["reviewerAuthorityDigest"],
                }
            )
            review["signature"] = _sign(
                _reviewer_private_key(factory, role),
                _review_signature_payload(
                    {
                        **{
                            key: lease[key]
                            for key in (
                                "projectExecutionKey",
                                "leaseId",
                                "attemptId",
                                "fencingToken",
                            )
                        },
                        "authoritySnapshotFingerprint": snapshot[
                            "snapshotFingerprint"
                        ],
                        "candidateIdentity": candidate_identity,
                    },
                    review,
                    required_reviewers,
                    minimum_verdict,
                ),
                _REVIEW_NAMESPACE,
            )
            review["evidenceDigest"] = _sha256(
                {
                    key: value
                    for key, value in review.items()
                    if key not in {"signature", "evidenceDigest"}
                }
            )
            review_set.append(review)

    reviewer_bindings = [
        {
            "reviewerRole": review["reviewerRole"],
            "reviewerId": review["reviewerId"],
            "reviewerAuthorityReference": review["reviewerAuthorityReference"],
            "reviewerAuthorityDigest": review["reviewerAuthorityDigest"],
            "reviewBindingDigest": review["reviewBindingDigest"],
        }
        for review in review_set
    ]
    proof = {
        "authorityId": lifecycle_authority["id"],
        "authorityReference": lifecycle_authority["path"],
        "authorityDigest": "sha256:" + lifecycle_authority["sha256"],
        "attemptId": lease["attemptId"],
        "expectedState": expected,
        "nextState": next_state,
        "candidateIdentity": copy.deepcopy(candidate_identity),
        "reviewBindingDigest": None
        if not review_set
        else _sha256([item["reviewBindingDigest"] for item in review_set]),
        "reviewEvidenceDigest": None if not review_set else _sha256(review_set),
        "reviewerAuthorityBindings": reviewer_bindings,
        "assertedAt": "2026-08-13T12:29:59Z",
        "signatureAlgorithm": "ED25519",
        "signatureFormat": "OPENSSH_SSHSIG_V1",
    }
    proof["signature"] = _sign(
        factory.lifecycle_private_key,
        {
            "schemaVersion": "controlled-lifecycle-signature-payload/v1",
            "authorityId": proof["authorityId"],
            "projectExecutionKey": lease["projectExecutionKey"],
            "leaseId": lease["leaseId"],
            "attemptId": lease["attemptId"],
            "fencingToken": lease["fencingToken"],
            "authoritySnapshotFingerprint": snapshot["snapshotFingerprint"],
            "expectedState": expected,
            "nextState": next_state,
            "candidateIdentity": candidate_identity,
            "reviewBindingDigest": proof["reviewBindingDigest"],
            "reviewEvidenceDigest": proof["reviewEvidenceDigest"],
            "assertedAt": proof["assertedAt"],
        },
        _LIFECYCLE_NAMESPACE,
    )
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
            "reviewEvidenceSet": review_set,
        }
    )


def _rebind_transition(factory, command, *, resign=True):
    review_set = command["reviewEvidenceSet"]
    required_reviewers, minimum_verdict = _acquired_review_policy(factory, command)
    for review in review_set:
        review["candidateIdentity"] = copy.deepcopy(command["candidateIdentity"])
        review["reviewBindingDigest"] = _sha256(
            {
                "candidateIdentity": command["candidateIdentity"],
                "projectExecutionKey": command["projectExecutionKey"],
                "leaseId": command["leaseId"],
                "attemptId": command["attemptId"],
                "fencingToken": command["fencingToken"],
                "authoritySnapshotFingerprint": command["authoritySnapshotFingerprint"],
                "reviewerId": review["reviewerId"],
                "reviewerRole": review["reviewerRole"],
                "reviewerAuthorityReference": review[
                    "reviewerAuthorityReference"
                ],
                "reviewerAuthorityDigest": review["reviewerAuthorityDigest"],
            }
        )
        review.update(
            {
                "candidateIdentity": copy.deepcopy(command["candidateIdentity"]),
                "projectExecutionKey": command["projectExecutionKey"],
                "leaseId": command["leaseId"],
                "attemptId": command["attemptId"],
                "fencingToken": command["fencingToken"],
                "authoritySnapshotFingerprint": command[
                    "authoritySnapshotFingerprint"
                ],
            }
        )
        if resign:
            review["signature"] = _sign(
                _reviewer_private_key(factory, review["reviewerRole"]),
                _review_signature_payload(
                    command, review, required_reviewers, minimum_verdict
                ),
                _REVIEW_NAMESPACE,
            )
        review["evidenceDigest"] = _sha256(
            {
                key: value
                for key, value in review.items()
                if key not in {"signature", "evidenceDigest"}
            }
        )
    reviewer_bindings = [
        {
            "reviewerRole": review["reviewerRole"],
            "reviewerId": review["reviewerId"],
            "reviewerAuthorityReference": review["reviewerAuthorityReference"],
            "reviewerAuthorityDigest": review["reviewerAuthorityDigest"],
            "reviewBindingDigest": review["reviewBindingDigest"],
        }
        for review in sorted(review_set, key=lambda item: item["reviewerRole"])
    ]
    proof = command["lifecycleAuthorityProof"]
    proof.update(
        {
            "attemptId": command["attemptId"],
            "expectedState": command["expectedState"],
            "nextState": command["nextState"],
            "candidateIdentity": copy.deepcopy(command["candidateIdentity"]),
            "reviewBindingDigest": None
            if not review_set
            else _sha256(
                [item["reviewBindingDigest"] for item in reviewer_bindings]
            ),
            "reviewEvidenceDigest": None
            if not review_set
            else _sha256(sorted(review_set, key=lambda item: item["reviewerRole"])),
            "reviewerAuthorityBindings": reviewer_bindings,
        }
    )
    if resign:
        proof["signature"] = _sign(
            factory.lifecycle_private_key,
            {
                "schemaVersion": "controlled-lifecycle-signature-payload/v1",
                "authorityId": proof["authorityId"],
                "projectExecutionKey": command["projectExecutionKey"],
                "leaseId": command["leaseId"],
                "attemptId": command["attemptId"],
                "fencingToken": command["fencingToken"],
                "authoritySnapshotFingerprint": command[
                    "authoritySnapshotFingerprint"
                ],
                "expectedState": command["expectedState"],
                "nextState": command["nextState"],
                "candidateIdentity": command["candidateIdentity"],
                "reviewBindingDigest": proof["reviewBindingDigest"],
                "reviewEvidenceDigest": proof["reviewEvidenceDigest"],
                "assertedAt": proof["assertedAt"],
            },
            _LIFECYCLE_NAMESPACE,
        )
    proof["proofDigest"] = _sha256(
        {key: value for key, value in proof.items() if key != "proofDigest"}
    )
    return _command_digest(command)


def _resign_lifecycle_only(factory, command):
    proof = command["lifecycleAuthorityProof"]
    proof["reviewEvidenceDigest"] = (
        None
        if not command["reviewEvidenceSet"]
        else _sha256(command["reviewEvidenceSet"])
    )
    proof["signature"] = _sign(
        factory.lifecycle_private_key,
        _lifecycle_signature_payload(command),
        _LIFECYCLE_NAMESPACE,
    )
    proof["proofDigest"] = _sha256(
        {key: value for key, value in proof.items() if key != "proofDigest"}
    )
    return _command_digest(command)


def _create_live_candidate(lease):
    lane = Path(lease["laneRoot"])
    head = subprocess.run(
        ["git", "-C", str(lane), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head == lease["expectedLaneBase"]:
        (lane / "candidate.txt").write_text("fixed candidate\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(lane), "add", "candidate.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(lane), "commit", "-qm", "fixed candidate"],
            check=True,
        )
    commit = subprocess.run(
        ["git", "-C", str(lane), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    parent = subprocess.run(
        ["git", "-C", str(lane), "rev-parse", "HEAD^"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "-C", str(lane), "rev-parse", "HEAD^{tree}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {"commit": commit, "parent": parent, "tree": tree}


def _commit_lane_file(lease, name="later.txt"):
    lane = Path(lease["laneRoot"])
    (lane / name).write_text(f"{name}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(lane), "add", name], check=True)
    subprocess.run(
        ["git", "-C", str(lane), "commit", "-qm", f"add {name}"], check=True
    )


def _acquire(factory, **changes):
    command = factory.acquire(create_lane=False, **changes)
    lane = Path(command["laneRoot"])
    lane.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "-q", "--no-hardlinks", str(factory.source_root), str(lane)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(lane), "config", "user.name", "Coordinator Test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(lane),
            "config",
            "user.email",
            "coordinator@example.test",
        ],
        check=True,
    )
    return coordinator.acquire_lane_lease(
        factory.repository_root,
        factory.source_root,
        command,
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
            assert result["candidateIdentity"] == command["candidateIdentity"]
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
    _rebind_transition(lifecycle_factory, other_attempt)
    with pytest.raises(ControlledCoordinationError) as mismatch:
        _transition(lifecycle_factory, other_attempt)
    assert mismatch.value.code == "LEASE_ATTEMPT_MISMATCH"
    assert lifecycle_factory.journal()["journalVersion"] == 1


def test_transition_requires_current_snapshot_and_authority_record(lifecycle_factory):
    lease = _acquire(lifecycle_factory)
    wrong_snapshot = _transition_command(lifecycle_factory, lease, "ACTIVE")
    wrong_snapshot["authoritySnapshotFingerprint"] = "sha256:" + "f" * 64
    _rebind_transition(lifecycle_factory, wrong_snapshot)
    with pytest.raises(ControlledCoordinationError) as fingerprint:
        _transition(lifecycle_factory, wrong_snapshot)
    assert fingerprint.value.code == "LIVE_AUTHORITY_SNAPSHOT_MISMATCH"

    wrong_authority = _transition_command(lifecycle_factory, lease, "ACTIVE")
    wrong_authority["lifecycleAuthorityProof"]["authorityDigest"] = (
        "sha256:" + "e" * 64
    )
    _rebind_transition(lifecycle_factory, wrong_authority)
    with pytest.raises(ControlledCoordinationError) as authority:
        _transition(lifecycle_factory, wrong_authority)
    assert authority.value.code == "LIFECYCLE_AUTHORITY_NOT_CURRENT"
    assert lifecycle_factory.journal()["journalVersion"] == 1


def test_lifecycle_signature_rejects_caller_rehashed_payload(lifecycle_factory):
    lease = _acquire(lifecycle_factory)
    forged = _transition_command(lifecycle_factory, lease, "ACTIVE")
    forged["nextState"] = "BLOCKED"
    _rebind_transition(lifecycle_factory, forged, resign=False)

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, forged)

    assert rejected.value.code == "LIFECYCLE_SIGNATURE_INVALID"
    assert lifecycle_factory.journal()["journalVersion"] == 1


def test_lifecycle_signature_rejects_wrong_authority_key(lifecycle_factory):
    lease = _acquire(lifecycle_factory)
    forged = _transition_command(lifecycle_factory, lease, "ACTIVE")
    original_key = lifecycle_factory.lifecycle_private_key
    lifecycle_factory.lifecycle_private_key = lifecycle_factory.reviewer_private_key
    try:
        _rebind_transition(lifecycle_factory, forged)
    finally:
        lifecycle_factory.lifecycle_private_key = original_key

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, forged)

    assert rejected.value.code == "LIFECYCLE_SIGNATURE_INVALID"
    assert lifecycle_factory.journal()["journalVersion"] == 1


def test_lifecycle_signature_rejects_authority_role_substitution(lifecycle_factory):
    lease = _acquire(lifecycle_factory)
    forged = _transition_command(lifecycle_factory, lease, "ACTIVE")
    _, authorities = _current_authorities(lifecycle_factory)
    reviewer = authorities["deep-reviewer"]
    proof = forged["lifecycleAuthorityProof"]
    proof["authorityId"] = reviewer["id"]
    proof["authorityReference"] = reviewer["path"]
    proof["authorityDigest"] = "sha256:" + reviewer["sha256"]
    original_key = lifecycle_factory.lifecycle_private_key
    lifecycle_factory.lifecycle_private_key = lifecycle_factory.reviewer_private_key
    try:
        _rebind_transition(lifecycle_factory, forged)
    finally:
        lifecycle_factory.lifecycle_private_key = original_key

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, forged)

    assert rejected.value.code == "LIFECYCLE_AUTHORITY_NOT_CURRENT"


def test_review_signature_and_required_role_are_fail_closed(lifecycle_factory):
    lease = _advance(lifecycle_factory, _acquire(lifecycle_factory), "ACTIVE")
    fixed = _transition(
        lifecycle_factory,
        _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE"),
    )
    wrong_role = _transition_command(lifecycle_factory, fixed, "REVIEW_GO")
    wrong_role["reviewEvidenceSet"][0]["reviewerRole"] = "ordinary-reviewer"
    _rebind_transition(lifecycle_factory, wrong_role)

    with pytest.raises(ControlledCoordinationError) as role_rejected:
        _transition(lifecycle_factory, wrong_role)

    assert role_rejected.value.code == "REVIEWER_POLICY_MISMATCH"


def test_review_signature_rejects_wrong_authority_key(lifecycle_factory):
    lease = _advance(lifecycle_factory, _acquire(lifecycle_factory), "ACTIVE")
    fixed = _transition(
        lifecycle_factory,
        _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE"),
    )
    forged = _transition_command(lifecycle_factory, fixed, "REVIEW_GO")
    original_key = lifecycle_factory.reviewer_private_key
    lifecycle_factory.reviewer_private_key = lifecycle_factory.lifecycle_private_key
    try:
        _rebind_transition(lifecycle_factory, forged)
    finally:
        lifecycle_factory.reviewer_private_key = original_key

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, forged)

    assert rejected.value.code == "REVIEW_SIGNATURE_INVALID"


def _multi_reviewer_fixed_lease(lifecycle_factory):
    lease = _advance(
        lifecycle_factory,
        _acquire(
            lifecycle_factory,
            descriptor_changes={
                "reviewPolicy": {
                    "reviewerRole": "lifecycle-controller",
                    "minimumVerdict": "GO_ZERO_FINDINGS",
                }
            },
        ),
        "ACTIVE",
    )
    return _transition(
        lifecycle_factory,
        _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE"),
    )


def test_review_go_verifies_complete_envelope_and_slice_reviewer_set(
    lifecycle_factory,
):
    fixed = _multi_reviewer_fixed_lease(lifecycle_factory)
    command = _transition_command(lifecycle_factory, fixed, "REVIEW_GO")

    result = _transition(lifecycle_factory, command)

    assert [
        item["reviewerRole"] for item in command["reviewEvidenceSet"]
    ] == ["deep-reviewer", "lifecycle-controller"]
    assert result["state"] == "REVIEW_GO"


@pytest.mark.parametrize("mutation", ["empty", "missing", "duplicate"])
def test_review_go_rejects_incomplete_or_duplicate_reviewer_set(
    lifecycle_factory, mutation
):
    fixed = _multi_reviewer_fixed_lease(lifecycle_factory)
    command = _transition_command(lifecycle_factory, fixed, "REVIEW_GO")
    if mutation == "empty":
        command["reviewEvidenceSet"] = []
        expected = "REVIEW_EVIDENCE_REQUIRED"
    elif mutation == "missing":
        command["reviewEvidenceSet"].pop()
        expected = "REVIEWER_POLICY_MISMATCH"
    else:
        command["reviewEvidenceSet"].append(
            copy.deepcopy(command["reviewEvidenceSet"][0])
        )
        expected = "COORDINATOR_COMMAND_INVALID"
    _rebind_transition(lifecycle_factory, command)

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, command)

    assert rejected.value.code == expected


@pytest.mark.parametrize("role", ["deep-reviewer", "lifecycle-controller"])
def test_each_required_reviewer_signature_is_independently_verified(
    lifecycle_factory, role
):
    fixed = _multi_reviewer_fixed_lease(lifecycle_factory)
    command = _transition_command(lifecycle_factory, fixed, "REVIEW_GO")
    required_reviewers, minimum_verdict = _acquired_review_policy(
        lifecycle_factory, command
    )
    review = next(
        item for item in command["reviewEvidenceSet"] if item["reviewerRole"] == role
    )
    wrong_key = (
        lifecycle_factory.reviewer_private_key
        if role == "lifecycle-controller"
        else lifecycle_factory.lifecycle_private_key
    )
    review["signature"] = _sign(
        wrong_key,
        _review_signature_payload(
            command, review, required_reviewers, minimum_verdict
        ),
        _REVIEW_NAMESPACE,
    )
    _resign_lifecycle_only(lifecycle_factory, command)

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, command)

    assert rejected.value.code == "REVIEW_SIGNATURE_INVALID"


def test_review_go_rejects_noncurrent_reviewer_authority_binding(
    lifecycle_factory,
):
    fixed = _multi_reviewer_fixed_lease(lifecycle_factory)
    command = _transition_command(lifecycle_factory, fixed, "REVIEW_GO")
    _, authorities = _current_authorities(lifecycle_factory)
    review = command["reviewEvidenceSet"][0]
    lifecycle_authority = authorities["lifecycle-controller"]
    review["reviewerAuthorityReference"] = lifecycle_authority["path"]
    review["reviewerAuthorityDigest"] = "sha256:" + lifecycle_authority["sha256"]
    _rebind_transition(lifecycle_factory, command)

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, command)

    assert rejected.value.code == "REVIEWER_AUTHORITY_NOT_CURRENT"


def test_review_go_rejects_review_time_after_lifecycle_assertion(
    lifecycle_factory,
):
    fixed = _multi_reviewer_fixed_lease(lifecycle_factory)
    command = _transition_command(lifecycle_factory, fixed, "REVIEW_GO")
    command["reviewEvidenceSet"][0]["reviewedAt"] = "2026-08-13T12:30:00Z"
    _rebind_transition(lifecycle_factory, command)

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, command)

    assert rejected.value.code == "REVIEWER_POLICY_MISMATCH"


@pytest.mark.parametrize("drift", ["digest", "owner", "mode"])
def test_sshsig_verifier_integrity_drift_fails_closed(
    lifecycle_factory, monkeypatch, drift
):
    lease = _acquire(lifecycle_factory)
    command = _transition_command(lifecycle_factory, lease, "ACTIVE")
    if drift == "digest":
        monkeypatch.setattr(coordinator, "_SSH_KEYGEN_SHA256", "0" * 64)
    else:
        verifier_descriptors = set()
        original_open = coordinator.os.open
        original_fstat = coordinator.os.fstat

        def tracking_open(path, *args, **kwargs):
            descriptor = original_open(path, *args, **kwargs)
            if path == "/usr/bin/ssh-keygen":
                verifier_descriptors.add(descriptor)
            return descriptor

        def drifted_fstat(descriptor):
            observed = original_fstat(descriptor)
            if descriptor not in verifier_descriptors:
                return observed
            fields = list(observed)
            if drift == "owner":
                fields[4] = 501
            else:
                fields[0] |= stat.S_IWGRP
            return os.stat_result(fields)

        monkeypatch.setattr(coordinator.os, "open", tracking_open)
        monkeypatch.setattr(coordinator.os, "fstat", drifted_fstat)

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, command)

    assert rejected.value.code == "SSH_KEYGEN_VERIFIER_INVALID"


def test_lifecycle_sshsig_rejects_wrong_namespace(lifecycle_factory):
    lease = _acquire(lifecycle_factory)
    forged = _transition_command(lifecycle_factory, lease, "ACTIVE")
    forged["lifecycleAuthorityProof"]["signature"] = _sign(
        lifecycle_factory.lifecycle_private_key,
        _lifecycle_signature_payload(forged),
        "agent-evolution-wrong-namespace-v1",
    )
    _rebind_transition(lifecycle_factory, forged, resign=False)

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, forged)

    assert rejected.value.code == "LIFECYCLE_SIGNATURE_INVALID"


def test_lifecycle_verifier_ignores_fake_path_success_executable(
    lifecycle_factory, tmp_path, monkeypatch
):
    lease = _acquire(lifecycle_factory)
    forged = _transition_command(lifecycle_factory, lease, "ACTIVE")
    forged["lifecycleAuthorityProof"]["signature"] = (
        "-----BEGIN SSH SIGNATURE-----\n"
        "U1NIU0lHAAAAAQ==\n"
        "-----END SSH SIGNATURE-----\n"
    )
    _rebind_transition(lifecycle_factory, forged, resign=False)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    for executable_name in ("openssl", "ssh-keygen"):
        fake_executable = fake_bin / executable_name
        fake_executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ["PATH"])

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, forged)

    assert rejected.value.code == "LIFECYCLE_SIGNATURE_INVALID"


def test_review_tampering_and_nonzero_findings_are_fail_closed(lifecycle_factory):
    lease = _advance(lifecycle_factory, _acquire(lifecycle_factory), "ACTIVE")
    fixed = _transition(
        lifecycle_factory,
        _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE"),
    )
    tampered_candidate = _transition_command(lifecycle_factory, fixed, "REVIEW_GO")
    tampered_candidate["candidateIdentity"]["tree"] = "7" * 40
    _rebind_transition(lifecycle_factory, tampered_candidate, resign=False)
    with pytest.raises(ControlledCoordinationError) as tampered:
        _transition(lifecycle_factory, tampered_candidate)
    assert tampered.value.code == "LIFECYCLE_SIGNATURE_INVALID"

    nonzero = _transition_command(lifecycle_factory, fixed, "REVIEW_GO")
    nonzero["reviewEvidenceSet"][0]["findingCounts"]["p1"] = 1
    _rebind_transition(lifecycle_factory, nonzero)
    with pytest.raises(ControlledCoordinationError) as findings:
        _transition(lifecycle_factory, nonzero)
    assert findings.value.code == "COORDINATOR_COMMAND_INVALID"


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


def test_transition_does_not_admit_uncommitted_lifecycle_key_via_ambient_git_view(
    lifecycle_factory, monkeypatch, tmp_path
):
    lease = _acquire(lifecycle_factory)
    replacement_public_key = Path(
        str(lifecycle_factory.reviewer_private_key) + ".pub"
    ).read_text(encoding="utf-8")
    key_type, key_body, *_ = replacement_public_key.split()
    (lifecycle_factory.source_root / "lifecycle-authority-public.pem").write_text(
        f"{key_type} {key_body}\n", encoding="utf-8"
    )
    _replace_head_with_worktree_tree(
        lifecycle_factory.source_root, "lifecycle-authority-public.pem"
    )
    invocation_log = _install_ambient_git_view(
        monkeypatch, tmp_path, lifecycle_factory.source_root
    )
    lifecycle_factory.lifecycle_private_key = lifecycle_factory.reviewer_private_key

    with pytest.raises(Exception) as caught:
        command = _transition_command(lifecycle_factory, lease, "ACTIVE")
        _transition(lifecycle_factory, command)

    assert getattr(caught.value, "code", None) in {
        "AUTHORITY_SOURCE_NOT_CLEAN_GIT",
        "ADMISSION_AUTHORITY_BINDING_MISMATCH",
        "AUTHORITY_SNAPSHOT_DRIFT",
        "LIVE_AUTHORITY_SNAPSHOT_MISMATCH",
    }
    assert not invocation_log.exists()


def test_fixed_candidate_and_review_are_immutable_and_current(lifecycle_factory):
    lease = _advance(lifecycle_factory, _acquire(lifecycle_factory), "ACTIVE")
    fixed = _transition(
        lifecycle_factory,
        _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE"),
    )
    assert fixed["candidateIdentity"] is not None

    changed_candidate = copy.deepcopy(fixed["candidateIdentity"])
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
    wrong_reviewer["reviewEvidenceSet"][0]["reviewerId"] = "reviewer:unregistered"
    _rebind_transition(lifecycle_factory, wrong_reviewer)
    with pytest.raises(ControlledCoordinationError) as reviewer:
        _transition(lifecycle_factory, wrong_reviewer)
    assert reviewer.value.code == "REVIEWER_POLICY_MISMATCH"

    review_go = _transition(
        lifecycle_factory,
        _transition_command(lifecycle_factory, fixed, "REVIEW_GO"),
    )
    assert review_go["candidateIdentity"] == fixed["candidateIdentity"]


@pytest.mark.parametrize("field", ["commit", "parent", "tree"])
def test_fixed_candidate_requires_exact_live_git_identity(lifecycle_factory, field):
    lease = _advance(lifecycle_factory, _acquire(lifecycle_factory), "ACTIVE")
    command = _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE")
    command["candidateIdentity"][field] = "7" * 40
    _rebind_transition(lifecycle_factory, command)

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, command)

    assert rejected.value.code == "LANE_CANDIDATE_INVALID"


def test_fixed_candidate_does_not_consume_transient_foreign_git_admin(
    lifecycle_factory, tmp_path, monkeypatch
):
    lease = _advance(lifecycle_factory, _acquire(lifecycle_factory), "ACTIVE")
    command = _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE")
    lane = Path(lease["laneRoot"])
    lane_admin = lane / ".git"
    held_lane_admin = tmp_path / "held-lane-candidate-admin"

    foreign = tmp_path / "foreign-candidate"
    foreign.mkdir()
    subprocess.run(["/usr/bin/git", "-C", str(foreign), "init", "-q"], check=True)
    subprocess.run(
        ["/usr/bin/git", "-C", str(foreign), "config", "user.name", "Foreign"],
        check=True,
    )
    subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(foreign),
            "config",
            "user.email",
            "foreign@example.test",
        ],
        check=True,
    )
    for name, contents in (("base.txt", "base\n"), ("foreign.txt", "foreign\n")):
        (foreign / name).write_text(contents, encoding="utf-8")
        subprocess.run(
            ["/usr/bin/git", "-C", str(foreign), "add", name], check=True
        )
        subprocess.run(
            ["/usr/bin/git", "-C", str(foreign), "commit", "-qm", name],
            check=True,
        )
    foreign_candidate = {
        field: subprocess.run(
            ["/usr/bin/git", "-C", str(foreign), "rev-parse", expression],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        for field, expression in (
            ("commit", "HEAD"),
            ("parent", "HEAD^"),
            ("tree", "HEAD^{tree}"),
        )
    }
    assert foreign_candidate != command["candidateIdentity"]
    command["candidateIdentity"] = foreign_candidate
    _rebind_transition(lifecycle_factory, command)

    foreign_admin = foreign / ".git"
    original_run = write_guard.subprocess.run
    hook_calls = 0

    def substitute_admin_only_during_git(*args, **kwargs):
        nonlocal hook_calls
        argv = args[0] if args else kwargs.get("args")
        if not argv or argv[0] != "/usr/bin/git":
            return original_run(*args, **kwargs)
        hook_calls += 1
        lane_admin.rename(held_lane_admin)
        foreign_admin.rename(lane_admin)
        try:
            return original_run(*args, **kwargs)
        finally:
            lane_admin.rename(foreign_admin)
            held_lane_admin.rename(lane_admin)

    monkeypatch.setattr(write_guard.subprocess, "run", substitute_admin_only_during_git)

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, command)

    assert rejected.value.code == "LANE_CANDIDATE_INVALID"
    assert hook_calls > 0


def test_fixed_candidate_admin_config_substitution_cannot_change_parent_or_tree(
    lifecycle_factory, tmp_path, monkeypatch
):
    lease = _advance(lifecycle_factory, _acquire(lifecycle_factory), "ACTIVE")
    command = _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE")
    expected_candidate = copy.deepcopy(command["candidateIdentity"])
    lane = Path(lease["laneRoot"])
    lane_admin = lane / ".git"
    held_lane_admin = tmp_path / "held-lane-admin"

    foreign = tmp_path / "foreign-bootstrap"
    foreign.mkdir()
    subprocess.run(["/usr/bin/git", "-C", str(foreign), "init", "-q"], check=True)
    subprocess.run(
        ["/usr/bin/git", "-C", str(foreign), "config", "user.name", "Foreign"],
        check=True,
    )
    subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(foreign),
            "config",
            "user.email",
            "foreign@example.test",
        ],
        check=True,
    )
    subprocess.run(
        ["/usr/bin/git", "-C", str(foreign), "config", "core.abbrev", "4"],
        check=True,
    )
    (foreign / "foreign.txt").write_text("foreign\n", encoding="utf-8")
    subprocess.run(
        ["/usr/bin/git", "-C", str(foreign), "add", "foreign.txt"], check=True
    )
    subprocess.run(
        ["/usr/bin/git", "-C", str(foreign), "commit", "-qm", "foreign"],
        check=True,
    )
    foreign_head = subprocess.run(
        ["/usr/bin/git", "-C", str(foreign), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    replacement_ref = (
        foreign / ".git" / "refs" / "replace" / expected_candidate["commit"]
    )
    replacement_ref.parent.mkdir(parents=True)
    replacement_ref.write_text(foreign_head + "\n", encoding="ascii")

    foreign_admin = foreign / ".git"
    original_run = write_guard.subprocess.run
    hook_calls = 0

    def substitute_admin_config_only_during_git(*args, **kwargs):
        nonlocal hook_calls
        argv = args[0] if args else kwargs.get("args")
        if not argv or argv[0] != "/usr/bin/git":
            return original_run(*args, **kwargs)
        hook_calls += 1
        lane_admin.rename(held_lane_admin)
        foreign_admin.rename(lane_admin)
        try:
            return original_run(*args, **kwargs)
        finally:
            lane_admin.rename(foreign_admin)
            held_lane_admin.rename(lane_admin)

    monkeypatch.setattr(
        write_guard.subprocess, "run", substitute_admin_config_only_during_git
    )

    fixed = _transition(lifecycle_factory, command)

    assert hook_calls > 0
    assert fixed["candidateIdentity"] == expected_candidate


def test_fixed_candidate_reads_held_objects_during_transient_path_substitution(
    lifecycle_factory, tmp_path, monkeypatch
):
    lease = _advance(lifecycle_factory, _acquire(lifecycle_factory), "ACTIVE")
    command = _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE")
    lane = Path(lease["laneRoot"])
    lane_objects = lane / ".git" / "objects"
    held_lane_objects = lane / ".git" / "objects-held"

    foreign = tmp_path / "foreign-object-view"
    foreign.mkdir()
    subprocess.run(["/usr/bin/git", "-C", str(foreign), "init", "-q"], check=True)
    foreign_objects = foreign / ".git" / "objects"
    original_run = write_guard.subprocess.run

    def substitute_objects_only_during_git(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args")
        if not argv or argv[0] != "/usr/bin/git":
            return original_run(*args, **kwargs)
        lane_objects.rename(held_lane_objects)
        foreign_objects.rename(lane_objects)
        try:
            return original_run(*args, **kwargs)
        finally:
            lane_objects.rename(foreign_objects)
            held_lane_objects.rename(lane_objects)

    monkeypatch.setattr(
        write_guard.subprocess, "run", substitute_objects_only_during_git
    )

    fixed = _transition(lifecycle_factory, command)

    assert fixed["candidateIdentity"] == command["candidateIdentity"]


def test_fixed_candidate_reads_packed_objects_from_held_object_root(
    lifecycle_factory,
):
    lease = _advance(lifecycle_factory, _acquire(lifecycle_factory), "ACTIVE")
    command = _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE")
    lane = Path(lease["laneRoot"])
    commit = command["candidateIdentity"]["commit"]
    loose_commit = lane / ".git" / "objects" / commit[:2] / commit[2:]
    assert loose_commit.is_file()
    subprocess.run(
        ["/usr/bin/git", "-C", str(lane), "gc", "--prune=now", "-q"], check=True
    )
    assert not loose_commit.exists()

    fixed = _transition(lifecycle_factory, command)

    assert fixed["candidateIdentity"] == command["candidateIdentity"]


def test_fixed_candidate_ignores_git_replace_object_view(lifecycle_factory):
    lease = _advance(lifecycle_factory, _acquire(lifecycle_factory), "ACTIVE")
    command = _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE")
    lane = Path(lease["laneRoot"])
    candidate = command["candidateIdentity"]
    replacement = subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(lane),
            "commit-tree",
            f"{candidate['parent']}^{{tree}}",
            "-p",
            candidate["parent"],
            "-m",
            "replacement object view",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(lane),
            "replace",
            candidate["commit"],
            replacement,
        ],
        check=True,
    )
    command["candidateIdentity"]["tree"] = subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(lane),
            "rev-parse",
            f"{candidate['commit']}^{{tree}}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _rebind_transition(lifecycle_factory, command)

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, command)

    assert rejected.value.code == "LANE_CANDIDATE_INVALID"


def test_fixed_candidate_rejects_git_admin_symlink_no_follow(lifecycle_factory):
    lease = _advance(lifecycle_factory, _acquire(lifecycle_factory), "ACTIVE")
    command = _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE")
    lane = Path(lease["laneRoot"])
    git_admin = lane / ".git"
    moved_admin = lane / ".git-real"
    git_admin.rename(moved_admin)
    git_admin.symlink_to(moved_admin, target_is_directory=True)

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, command)

    assert rejected.value.code == "LANE_CANDIDATE_INVALID"


def test_candidate_bound_transition_rejects_live_head_advance(lifecycle_factory):
    lease = _advance(lifecycle_factory, _acquire(lifecycle_factory), "ACTIVE")
    fixed = _transition(
        lifecycle_factory,
        _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE"),
    )
    _commit_lane_file(fixed)

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(
            lifecycle_factory,
            _transition_command(lifecycle_factory, fixed, "REVIEW_GO"),
        )

    assert rejected.value.code == "LANE_CANDIDATE_INVALID"


def test_exact_candidate_replay_revalidates_live_git(lifecycle_factory):
    lease = _advance(lifecycle_factory, _acquire(lifecycle_factory), "ACTIVE")
    command = _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE")
    fixed = _transition(lifecycle_factory, command)
    _commit_lane_file(fixed, "after-replay.txt")

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, copy.deepcopy(command))

    assert rejected.value.code == "LANE_CANDIDATE_INVALID"


@pytest.mark.parametrize("replacement_kind", ["directory", "symlink"])
def test_fixed_candidate_rejects_lane_physical_drift(
    lifecycle_factory, replacement_kind
):
    lease = _advance(lifecycle_factory, _acquire(lifecycle_factory), "ACTIVE")
    command = _transition_command(lifecycle_factory, lease, "FIXED_CANDIDATE")
    lane = Path(lease["laneRoot"])
    moved = lane.with_name(lane.name + "-moved")
    lane.rename(moved)
    if replacement_kind == "directory":
        lane.mkdir()
    else:
        lane.symlink_to(moved, target_is_directory=True)

    with pytest.raises(ControlledCoordinationError) as rejected:
        _transition(lifecycle_factory, command)

    assert rejected.value.code == "LANE_ROOT_IDENTITY_CHANGED"


def test_cancel_requires_current_authority(lifecycle_factory):
    lease = _acquire(lifecycle_factory)
    missing_authority = _transition_command(lifecycle_factory, lease, "CANCELLED")
    missing_authority["lifecycleAuthorityProof"]["authorityReference"] = (
        "authority/missing.yaml"
    )
    _rebind_transition(lifecycle_factory, missing_authority)
    with pytest.raises(ControlledCoordinationError) as authority:
        _transition(lifecycle_factory, missing_authority)
    assert authority.value.code == "LIFECYCLE_AUTHORITY_NOT_CURRENT"


@pytest.mark.parametrize("process_mode", ["empty", "live"])
def test_cancel_retains_capacity_until_recovery(lifecycle_factory, process_mode):
    lease = _acquire(lifecycle_factory, max_parallel_lanes=1)
    live_process = None
    command = _transition_command(lifecycle_factory, lease, "CANCELLED")
    if process_mode == "live":
        live_process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"]
        )
        command["processQuiescence"]["processIds"] = [live_process.pid]
        _rebind_transition(lifecycle_factory, command)
    try:
        cancelled = _transition(lifecycle_factory, command)
    finally:
        if live_process is not None:
            live_process.terminate()
            live_process.wait(timeout=10)

    journal = lifecycle_factory.journal()
    assert cancelled["state"] == "CANCELLED"
    assert cancelled["released"] is False
    assert cancelled["leaseRetained"] is True
    assert journal["nextFencingToken"] > lease["fencingToken"]

    with pytest.raises(ControlledCoordinationError) as capacity:
        coordinator.acquire_lane_lease(
            lifecycle_factory.repository_root,
            lifecycle_factory.source_root,
            lifecycle_factory.acquire(
                slice_id="slice:neutral-b",
                attempt_id="attempt:neutral-b",
                owner="owner:neutral-b",
                exact_write_set="services/neutral-b",
                max_parallel_lanes=1,
            ),
        )
    assert capacity.value.code == "PROJECT_CAPACITY_LIMIT"

    changed = _transition_command(
        lifecycle_factory, cancelled, "ACTIVE", expected_state="CANCELLED"
    )
    with pytest.raises(ControlledCoordinationError) as terminal:
        _transition(lifecycle_factory, changed)
    assert terminal.value.code == "INVALID_STATE_TRANSITION"


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
    _rebind_transition(lifecycle_factory, changed)
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
