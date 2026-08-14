from __future__ import annotations

import copy
import json
from dataclasses import dataclass

import pytest

from evolution_harness.controlled_coordinator_inputs import (
    ControlledCoordinationError,
    normalize_acquire_command,
    normalize_recovery_command,
    normalize_transition_command,
    normalize_write_observation_command,
)
from evolution_harness.controlled_inputs import descriptor_digest, envelope_digest
from evolution_harness.controlled_planner import build_provisional_execution_plan
from evolution_harness.hashing import canonical_json_bytes, sha256_bytes
from evolution_harness.schema import SchemaStore, SchemaValidationError


_FAKE_SSHSIG = (
    "-----BEGIN SSH SIGNATURE-----\n"
    "U1NIU0lHAAAAAQ==\n"
    "-----END SSH SIGNATURE-----\n"
)
_FAKE_RECOVERY_PUBLIC_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG499f9tuCPdF5QqO6WvLXbLcP/NpaFR3tQg9zo8XtWl\n"
)


def _sha256(value):
    return "sha256:" + sha256_bytes(canonical_json_bytes(value))


def _with_command_digest(command):
    value = copy.deepcopy(command)
    value["commandDigest"] = _sha256(
        {key: item for key, item in value.items() if key != "commandDigest"}
    )
    return value


def _refresh_batch_plan_id(plan):
    plan["batchPlanId"] = (
        "batch-plan:"
        + sha256_bytes(
            canonical_json_bytes(
                {key: value for key, value in plan.items() if key != "batchPlanId"}
            )
        )[:24]
    )


def _refresh_footprint_id(command):
    footprint = command["fullFootprint"]
    footprint["conflictFootprintId"] = (
        "footprint:"
        + sha256_bytes(
            canonical_json_bytes(
                {
                    "projectId": command["projectId"],
                    "conflictPolicyVersion": command["conflictPolicyVersion"],
                    **{
                        key: value
                        for key, value in footprint.items()
                        if key != "conflictFootprintId"
                    },
                }
            )
        )[:24]
    )


def _refresh_acquire_snapshot_and_plan(command):
    snapshot = command["authoritySnapshot"]
    snapshot["sourceRevision"]["authoritySetDigest"] = _sha256(
        snapshot["authorities"]
    )
    snapshot["snapshotFingerprint"] = _sha256(
        {
            key: value
            for key, value in snapshot.items()
            if key != "snapshotFingerprint"
        }
    )
    command["authoritySnapshotFingerprint"] = snapshot["snapshotFingerprint"]
    command["executionPlan"]["authoritySnapshotFingerprint"] = snapshot[
        "snapshotFingerprint"
    ]
    _refresh_batch_plan_id(command["executionPlan"])
    command["batchPlanId"] = command["executionPlan"]["batchPlanId"]


def _forge_acquire_descriptor(command, **changes):
    descriptor = command["sliceDescriptor"]
    descriptor.update(changes)
    descriptor["descriptorDigest"] = descriptor_digest(descriptor)
    command["fullFootprint"] = {
        **command["fullFootprint"],
        **{
            field: copy.deepcopy(descriptor[field])
            for field in (
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
        },
    }
    _refresh_footprint_id(command)
    admission = command["executionPlan"]["proposedAdmissions"][0]
    admission["descriptorDigest"] = descriptor["descriptorDigest"]
    admission["exactWriteSetDigest"] = _sha256(sorted(descriptor["exactWriteSet"]))
    descriptor_fact = command["authoritySnapshot"]["facts"][
        "controlled_planning.slice_descriptor_digests"
    ]
    descriptor_fact["rawValue"] = canonical_json_bytes(
        [descriptor["descriptorDigest"]]
    ).decode("utf-8")
    descriptor_fact["normalizedValue"] = descriptor_fact["rawValue"]
    if "planningRequest" in command:
        command["planningRequest"]["slices"] = [copy.deepcopy(descriptor)]
        command["planningRequest"]["dependencyGraphDigest"] = command[
            "executionPlan"
        ]["dependencyGraphDigest"]
        command["planningRequest"]["authoritySnapshot"] = copy.deepcopy(
            command["authoritySnapshot"]
        )
    _refresh_acquire_snapshot_and_plan(command)
    if "planningRequest" in command:
        command["planningRequest"]["authoritySnapshot"] = copy.deepcopy(
            command["authoritySnapshot"]
        )


@dataclass
class CoordinatorFactory:
    repository_root: object
    controlled_factory: object

    def _plan_bundle(self, *, action_class="action:ordinary-development"):
        descriptor = self.controlled_factory.descriptor(
            authorizationClass=action_class,
        )
        envelope = self.controlled_factory.envelope(
            permittedActionClasses=[action_class],
            deniedActions=[],
        )
        envelope["permittedPathPrefixes"] = sorted(envelope["permittedPathPrefixes"])
        return build_provisional_execution_plan(
            self.repository_root,
            self.controlled_factory.request(descriptor, envelope=envelope),
        )

    def acquire(
        self,
        *,
        action_class="action:ordinary-development",
        descriptor_changes=None,
        **changes,
    ):
        descriptor = self.controlled_factory.descriptor(
            authorizationClass=action_class,
            **(descriptor_changes or {}),
        )
        envelope = self.controlled_factory.envelope(
            permittedActionClasses=[action_class],
            deniedActions=[],
        )
        envelope["permittedPathPrefixes"] = sorted(envelope["permittedPathPrefixes"])
        binding = {
            "projectId": "neutral-project",
            "sliceId": descriptor["sliceId"],
            "attemptId": "attempt:neutral-a",
            "originalSourceRoot": "/projects/neutral",
            "laneRoot": "/projects/neutral-lanes/slice-neutral-a",
        }
        request = self.controlled_factory.request(descriptor, envelope=envelope)
        fact_id = f"controlled_coordination.admission.{descriptor['sliceId']}"
        request["authoritySnapshot"]["facts"][fact_id] = {
            "owner": "authority-planning",
            "sourcePath": "authority/controlled-planning.yaml",
            "rawValue": canonical_json_bytes(binding).decode("utf-8"),
            "normalizedValue": canonical_json_bytes(binding).decode("utf-8"),
        }
        request["authoritySnapshot"]["snapshotFingerprint"] = _sha256(
            {
                key: value
                for key, value in request["authoritySnapshot"].items()
                if key != "snapshotFingerprint"
            }
        )
        bundle = build_provisional_execution_plan(self.repository_root, request)
        plan = bundle["executionPlan"]
        footprint = next(
            item
            for item in bundle["conflictReport"]["footprints"]
            if item["sliceId"] == "slice:neutral-a"
        )
        authority_proof = {
            "factId": fact_id,
            "manifestAuthorityId": "authority-planning",
            "manifestAuthorityReference": "authority/controlled-planning.yaml",
            "manifestAuthorityDigest": "sha256:" + "6" * 64,
            "binding": binding,
        }
        authority_proof["proofDigest"] = _sha256(authority_proof)
        value = {
            "schemaVersion": "controlled-coordinator-acquire-command/v1",
            "projectId": plan["projectId"],
            "batchPlanId": plan["batchPlanId"],
            "sliceId": "slice:neutral-a",
            "attemptId": "attempt:neutral-a",
            "authoritySnapshotFingerprint": plan[
                "authoritySnapshotFingerprint"
            ],
            "authorizationEnvelopeDigest": plan[
                "authorizationEnvelopeDigest"
            ],
            "conflictPolicyVersion": plan["conflictPolicyVersion"],
            "asOf": plan["asOf"],
            "planningRequest": request,
            "executionPlan": plan,
            "sliceDescriptor": descriptor,
            "authorizationEnvelope": envelope,
            "authoritySnapshot": request["authoritySnapshot"],
            "admissionAuthorityProof": authority_proof,
            "fullFootprint": footprint,
            "originalSourceRoot": "/projects/neutral",
            "laneRoot": "/projects/neutral-lanes/slice-neutral-a",
            "expectedLaneBase": plan["batchBaseCommit"],
        }
        value.update(copy.deepcopy(changes))
        return _with_command_digest(value)

    def transition(self, **changes):
        value = {
            "schemaVersion": "controlled-coordinator-transition-command/v1",
            "projectExecutionKey": "project-execution:" + "1" * 64,
            "leaseId": "lease:" + "2" * 24,
            "attemptId": "attempt:neutral-a",
            "fencingToken": 7,
            "expectedState": "ACTIVE",
            "nextState": "FIXED_CANDIDATE",
            "authoritySnapshotFingerprint": "sha256:" + "3" * 64,
            "candidateIdentity": {
                "commit": "4" * 40,
                "parent": "5" * 40,
                "tree": "6" * 40,
            },
            "processQuiescence": {
                "status": "QUIESCENT",
                "observedAt": "2026-08-13T12:30:00Z",
                "processIds": [],
            },
        }
        value.update(copy.deepcopy(changes))
        if "reviewEvidence" not in value:
            value["reviewEvidence"] = None
            if value["nextState"] == "REVIEW_GO":
                review = {
                    "candidateIdentity": copy.deepcopy(value["candidateIdentity"]),
                    "reviewerId": "deep-reviewer",
                    "reviewerRole": "deep-reviewer",
                    "projectExecutionKey": value["projectExecutionKey"],
                    "leaseId": value["leaseId"],
                    "attemptId": value["attemptId"],
                    "fencingToken": value["fencingToken"],
                    "authoritySnapshotFingerprint": value[
                        "authoritySnapshotFingerprint"
                    ],
                    "reviewerAuthorityReference": "deep-reviewer-public.pem",
                    "reviewerAuthorityDigest": "sha256:" + "b" * 64,
                    "verdict": "GO_ZERO_FINDINGS",
                    "findingCounts": {"p0": 0, "p1": 0, "p2": 0},
                    "reviewedAt": "2026-08-13T12:29:30Z",
                    "signatureAlgorithm": "ED25519",
                    "signatureFormat": "OPENSSH_SSHSIG_V1",
                    "signature": _FAKE_SSHSIG,
                }
                review["reviewBindingDigest"] = _sha256(
                    {
                        "candidateIdentity": value["candidateIdentity"],
                        "projectExecutionKey": value["projectExecutionKey"],
                        "leaseId": value["leaseId"],
                        "attemptId": value["attemptId"],
                        "fencingToken": value["fencingToken"],
                        "authoritySnapshotFingerprint": value["authoritySnapshotFingerprint"],
                        "reviewerId": review["reviewerId"],
                        "reviewerRole": review["reviewerRole"],
                        "reviewerAuthorityReference": review[
                            "reviewerAuthorityReference"
                        ],
                        "reviewerAuthorityDigest": review[
                            "reviewerAuthorityDigest"
                        ],
                    }
                )
                review["evidenceDigest"] = _sha256(review)
                value["reviewEvidence"] = review
        review = value["reviewEvidence"]
        authority_proof = value.get("lifecycleAuthorityProof") or {
            "authorityId": "lifecycle-controller",
            "authorityReference": "lifecycle-authority-public.pem",
            "authorityDigest": "sha256:" + "a" * 64,
            "attemptId": value["attemptId"],
            "expectedState": value["expectedState"],
            "nextState": value["nextState"],
            "candidateIdentity": copy.deepcopy(value["candidateIdentity"]),
            "reviewBindingDigest": (
                review["reviewBindingDigest"] if review is not None else None
            ),
            "reviewEvidenceDigest": (
                review["evidenceDigest"] if review is not None else None
            ),
            "reviewerId": review["reviewerId"] if review is not None else None,
            "reviewerAuthorityReference": (
                review["reviewerAuthorityReference"] if review is not None else None
            ),
            "reviewerAuthorityDigest": (
                review["reviewerAuthorityDigest"] if review is not None else None
            ),
            "assertedAt": "2026-08-13T12:29:00Z",
            "signatureAlgorithm": "ED25519",
            "signatureFormat": "OPENSSH_SSHSIG_V1",
            "signature": _FAKE_SSHSIG,
        }
        authority_proof["proofDigest"] = _sha256(
            {
                key: item
                for key, item in authority_proof.items()
                if key != "proofDigest"
            }
        )
        value["lifecycleAuthorityProof"] = authority_proof
        return _with_command_digest(value)

    def observation(self, **changes):
        value = {
            "schemaVersion": "controlled-write-observation-command/v1",
            "projectExecutionKey": "project-execution:" + "1" * 64,
            "leaseId": "lease:" + "2" * 24,
            "fencingToken": 7,
            "beforeInventoryDigest": "sha256:" + "7" * 64,
            "observedPaths": ["services/neutral-a/a.py", "services/neutral-a/b.py"],
            "ephemeralPathsRemoved": ["build/neutral-a/cache"],
            "processQuiescence": {
                "status": "QUIESCENT",
                "observedAt": "2026-08-13T12:31:00Z",
                "processIds": [],
            },
        }
        value.update(copy.deepcopy(changes))
        return _with_command_digest(value)

    def recovery(self, **changes):
        value = {
            "schemaVersion": "controlled-recovery-command/v1",
            "projectExecutionKey": "project-execution:" + "1" * 64,
            "recoveryId": "recovery:" + "8" * 24,
            "recoveryAuthorityId": "recovery-controller",
            "recoveryAuthorityReference": "authority/recovery.yaml",
            "recoveryAuthorityDigest": "sha256:" + "9" * 64,
            "recoveryAuthorityPublicKey": _FAKE_RECOVERY_PUBLIC_KEY,
            "signatureAlgorithm": "ED25519",
            "signatureFormat": "OPENSSH_SSHSIG_V1",
            "signature": _FAKE_SSHSIG,
            "expectedJournalVersion": 11,
            "processQuiescenceProofs": [
                {
                    "leaseId": "lease:" + "2" * 24,
                    "fencingToken": 7,
                    "status": "QUIESCENT",
                    "observedAt": "2026-08-13T12:32:00Z",
                }
            ],
            "observedWriteSet": [
                "services/neutral-a/a.py",
                "services/neutral-a/b.py",
            ],
            "affectedLeaseDecisions": [
                {
                    "leaseId": "lease:" + "2" * 24,
                    "decision": "STALE",
                    "reason": "WRITESET_OVERLAP",
                }
            ],
            "replacementPlanRequired": True,
        }
        value.update(copy.deepcopy(changes))
        return _with_command_digest(value)


@pytest.fixture
def coordinator_factory(repository_root, controlled_factory):
    return CoordinatorFactory(repository_root, controlled_factory)


def _mutate_acquire(command, field):
    changed_descriptor = copy.deepcopy(command["sliceDescriptor"])
    changed_descriptor["priority"] += 1
    changed_descriptor["descriptorDigest"] = descriptor_digest(changed_descriptor)
    changed_envelope = copy.deepcopy(command["authorizationEnvelope"])
    changed_envelope["maxParallelLanes"] = 2
    changed_envelope["envelopeDigest"] = envelope_digest(changed_envelope)
    changed_snapshot = copy.deepcopy(command["authoritySnapshot"])
    changed_snapshot["facts"]["controlled_coordination.extra"] = {
        "owner": "authority-neutral",
        "sourcePath": "authority/portfolio.yaml",
        "rawValue": "changed",
        "normalizedValue": "changed",
    }
    changed_snapshot["snapshotFingerprint"] = _sha256(
        {
            key: value
            for key, value in changed_snapshot.items()
            if key != "snapshotFingerprint"
        }
    )
    changed_proof = copy.deepcopy(command["admissionAuthorityProof"])
    changed_proof["manifestAuthorityDigest"] = "sha256:" + "c" * 64
    changed_proof["proofDigest"] = _sha256(
        {key: value for key, value in changed_proof.items() if key != "proofDigest"}
    )
    mutations = {
        "projectId": "neutral-project-changed",
        "batchPlanId": "batch-plan:" + "a" * 24,
        "sliceId": "slice:changed",
        "attemptId": "attempt:changed",
        "authoritySnapshotFingerprint": "sha256:" + "a" * 64,
        "authorizationEnvelopeDigest": "sha256:" + "b" * 64,
        "conflictPolicyVersion": "controlled-conflict-policy/v2",
        "asOf": "2026-08-13T12:00:01Z",
        "planningRequest": {
            **command["planningRequest"],
            "asOf": "2026-08-13T12:00:01Z",
        },
        "executionPlan": {**command["executionPlan"], "asOf": "2026-08-13T12:00:01Z"},
        "sliceDescriptor": changed_descriptor,
        "authorizationEnvelope": changed_envelope,
        "authoritySnapshot": changed_snapshot,
        "admissionAuthorityProof": changed_proof,
        "fullFootprint": {**command["fullFootprint"], "ownerSet": ["owner:changed"]},
        "originalSourceRoot": "/projects/changed",
        "laneRoot": "/projects/neutral-lanes/changed",
        "expectedLaneBase": "c" * 40,
    }
    command[field] = mutations[field]


@pytest.mark.parametrize(
    "field",
    [
        "projectId",
        "batchPlanId",
        "sliceId",
        "attemptId",
        "authoritySnapshotFingerprint",
        "authorizationEnvelopeDigest",
        "conflictPolicyVersion",
        "asOf",
        "planningRequest",
        "executionPlan",
        "sliceDescriptor",
        "authorizationEnvelope",
        "authoritySnapshot",
        "admissionAuthorityProof",
        "fullFootprint",
        "originalSourceRoot",
        "laneRoot",
        "expectedLaneBase",
    ],
)
def test_acquire_digest_binds_every_authority_field(
    repository_root, coordinator_factory, field
):
    command = coordinator_factory.acquire()
    _mutate_acquire(command, field)

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_acquire_command(repository_root, command)

    expected = (
        "COORDINATOR_COMMAND_INVALID"
        if field == "conflictPolicyVersion"
        else "COMMAND_DIGEST_MISMATCH"
    )
    assert caught.value.code == expected


def test_acquire_rejects_unknown_field_and_digest_mutation(
    repository_root, coordinator_factory
):
    command = coordinator_factory.acquire()
    command["surprise"] = True
    with pytest.raises(ControlledCoordinationError) as unknown:
        normalize_acquire_command(repository_root, command)
    assert unknown.value.code == "COORDINATOR_COMMAND_INVALID"

    command = coordinator_factory.acquire()
    command["attemptId"] = "attempt:changed"
    with pytest.raises(ControlledCoordinationError) as changed:
        normalize_acquire_command(repository_root, command)
    assert changed.value.code == "COMMAND_DIGEST_MISMATCH"


def test_acquire_deep_copies_and_canonicalizes_only_footprint_sets(
    repository_root, coordinator_factory
):
    command = coordinator_factory.acquire(
        descriptor_changes={
            "ownerSet": ["owner:z", "owner:a"],
            "producerConsumerSet": [
                {"producer": "owner:z", "consumer": "owner:a"},
                {"producer": "owner:a", "consumer": "owner:z"},
            ],
        }
    )
    unsorted_owners = ["owner:z", "owner:a"]
    unsorted_relations = [
        {"producer": "owner:z", "consumer": "owner:a"},
        {"producer": "owner:a", "consumer": "owner:z"},
    ]
    command["sliceDescriptor"]["ownerSet"] = unsorted_owners
    command["sliceDescriptor"]["producerConsumerSet"] = unsorted_relations
    command["fullFootprint"]["ownerSet"] = unsorted_owners
    command["fullFootprint"]["producerConsumerSet"] = unsorted_relations
    digest_payload = copy.deepcopy(command)
    digest_payload["sliceDescriptor"]["ownerSet"] = ["owner:a", "owner:z"]
    digest_payload["sliceDescriptor"]["producerConsumerSet"] = [
        {"producer": "owner:a", "consumer": "owner:z"},
        {"producer": "owner:z", "consumer": "owner:a"},
    ]
    digest_payload["fullFootprint"]["ownerSet"] = ["owner:a", "owner:z"]
    digest_payload["fullFootprint"]["producerConsumerSet"] = [
        {"producer": "owner:a", "consumer": "owner:z"},
        {"producer": "owner:z", "consumer": "owner:a"},
    ]
    command["commandDigest"] = _sha256(
        {key: value for key, value in digest_payload.items() if key != "commandDigest"}
    )
    original = copy.deepcopy(command)

    normalized = normalize_acquire_command(repository_root, command)

    assert command == original
    assert normalized["fullFootprint"]["ownerSet"] == ["owner:a", "owner:z"]
    assert normalized["fullFootprint"]["producerConsumerSet"] == [
        {"producer": "owner:a", "consumer": "owner:z"},
        {"producer": "owner:z", "consumer": "owner:a"},
    ]
    assert normalized["executionPlan"]["executionRequirements"]["requiredGates"] == [
        "unit",
        "integration",
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("originalSourceRoot", "/projects/neutral/../neutral"),
        ("originalSourceRoot", "//projects/neutral"),
        ("laneRoot", "/projects//neutral-lanes/slice-neutral-a"),
        ("laneRoot", "//projects/neutral-lanes/slice-neutral-a"),
    ],
)
def test_acquire_rejects_absolute_path_aliases(
    repository_root, coordinator_factory, field, value
):
    command = coordinator_factory.acquire(**{field: value})

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_acquire_command(repository_root, command)

    assert caught.value.code == "UNSAFE_COORDINATOR_PATH"


def test_acquire_rejects_relative_path_aliases_and_duplicates(
    repository_root, coordinator_factory
):
    for paths in (
        ["services//neutral-a"],
        ["services/neutral-a", "services//neutral-a"],
    ):
        command = coordinator_factory.acquire()
        command["fullFootprint"]["exactWriteSet"] = paths
        command = _with_command_digest(command)
        with pytest.raises(ControlledCoordinationError) as caught:
            normalize_acquire_command(repository_root, command)
        assert caught.value.code == "UNSAFE_COORDINATOR_PATH"


def test_acquire_rejects_self_consistent_footprint_forged_away_from_descriptor(
    repository_root, coordinator_factory
):
    command = coordinator_factory.acquire()
    command["fullFootprint"]["ownerSet"] = ["owner:forged"]
    _refresh_footprint_id(command)
    command = _with_command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_acquire_command(repository_root, command)

    assert caught.value.code == "EXECUTION_PLAN_BINDING_MISMATCH"


def test_acquire_rejects_self_consistent_descriptor_not_bound_to_snapshot_fact(
    repository_root, controlled_factory, coordinator_factory
):
    command = coordinator_factory.acquire()
    descriptor = controlled_factory.descriptor(ownerSet=["owner:forged"])
    command["sliceDescriptor"] = descriptor
    command["fullFootprint"]["ownerSet"] = descriptor["ownerSet"]
    _refresh_footprint_id(command)
    command["executionPlan"]["proposedAdmissions"][0]["descriptorDigest"] = (
        descriptor["descriptorDigest"]
    )
    _refresh_batch_plan_id(command["executionPlan"])
    command["batchPlanId"] = command["executionPlan"]["batchPlanId"]
    command = _with_command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_acquire_command(repository_root, command)

    assert caught.value.code == "ADMISSION_AUTHORITY_BINDING_MISMATCH"


def test_acquire_rejects_dirty_authority_snapshot_even_when_rehashed(
    repository_root, coordinator_factory
):
    command = coordinator_factory.acquire()
    snapshot = command["authoritySnapshot"]
    snapshot["sourceRevision"]["authoritySetStatus"] = "DIRTY_AUTHORITY_SET"
    snapshot["snapshotFingerprint"] = _sha256(
        {
            key: value
            for key, value in snapshot.items()
            if key != "snapshotFingerprint"
        }
    )
    command["authoritySnapshotFingerprint"] = snapshot["snapshotFingerprint"]
    command["executionPlan"]["authoritySnapshotFingerprint"] = snapshot[
        "snapshotFingerprint"
    ]
    _refresh_batch_plan_id(command["executionPlan"])
    command["batchPlanId"] = command["executionPlan"]["batchPlanId"]
    command = _with_command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_acquire_command(repository_root, command)

    assert caught.value.code == "AUTHORITY_SOURCE_NOT_CLEAN_GIT"


def test_acquire_rejects_protected_descriptor_forged_into_proposed_admissions(
    repository_root, coordinator_factory
):
    action_class = "action:database-write"
    command = coordinator_factory.acquire(action_class=action_class)
    plan = command["executionPlan"]
    descriptor = command["sliceDescriptor"]
    footprint = command["fullFootprint"]
    plan["proposedAdmissions"] = [
        {
            "sliceId": descriptor["sliceId"],
            "conflictClusterId": "conflict-cluster:" + "f" * 24,
            "descriptorDigest": descriptor["descriptorDigest"],
            "exactWriteSetDigest": _sha256(sorted(footprint["exactWriteSet"])),
        }
    ]
    plan["rejected"] = []
    _refresh_batch_plan_id(plan)
    command["batchPlanId"] = plan["batchPlanId"]
    command = _with_command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_acquire_command(repository_root, command)

    assert caught.value.code == "PROTECTED_ACTION_DENIED"


@pytest.mark.parametrize(
    ("descriptor_changes", "planner_reason"),
    [
        ({"state": "PROPOSED"}, "SLICE_NOT_READY"),
        ({"exactWriteSet": ["outside/source"]}, "WRITESET_OUTSIDE_PREFIX"),
        ({"portfolioId": "portfolio:forged"}, "PORTFOLIO_NOT_PERMITTED"),
        ({"deliveryTrackId": "track:forged"}, "DELIVERY_TRACK_NOT_PERMITTED"),
        ({"sliceClass": "class:forged"}, "SLICE_CLASS_NOT_PERMITTED"),
    ],
)
def test_acquire_replays_phase1a_authorization_instead_of_trusting_forged_plan(
    repository_root,
    coordinator_factory,
    descriptor_changes,
    planner_reason,
):
    command = coordinator_factory.acquire()
    _forge_acquire_descriptor(command, **descriptor_changes)
    command = _with_command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_acquire_command(repository_root, command)

    assert caught.value.code == "EXECUTION_PLAN_BINDING_MISMATCH"
    assert planner_reason in str(caught.value)


def test_acquire_replays_phase1a_envelope_expiry(repository_root, coordinator_factory):
    command = coordinator_factory.acquire()
    expired_as_of = "2026-08-14T00:00:00Z"
    command["asOf"] = expired_as_of
    command["planningRequest"]["asOf"] = expired_as_of
    command["executionPlan"]["asOf"] = expired_as_of
    _refresh_batch_plan_id(command["executionPlan"])
    command["batchPlanId"] = command["executionPlan"]["batchPlanId"]
    command = _with_command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_acquire_command(repository_root, command)

    assert caught.value.code == "EXECUTION_PLAN_BINDING_MISMATCH"
    assert "ENVELOPE_EXPIRED" in str(caught.value)


@pytest.mark.parametrize("authority_mutation", ["path_alias", "duplicate_id"])
def test_acquire_rejects_self_consistent_noncanonical_authority_records(
    repository_root, coordinator_factory, authority_mutation
):
    command = coordinator_factory.acquire()
    snapshot = command["authoritySnapshot"]
    if authority_mutation == "path_alias":
        snapshot["authorities"][1]["path"] = "authority//slice-neutral-a.yaml"
    else:
        snapshot["authorities"][1]["id"] = snapshot["authorities"][0]["id"]
    if "planningRequest" in command:
        command["planningRequest"]["authoritySnapshot"] = copy.deepcopy(snapshot)
    _refresh_acquire_snapshot_and_plan(command)
    if "planningRequest" in command:
        command["planningRequest"]["authoritySnapshot"] = copy.deepcopy(snapshot)
    command = _with_command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_acquire_command(repository_root, command)

    assert caught.value.code in {
        "AUTHORITY_RECORD_DUPLICATE",
        "UNSAFE_COORDINATOR_PATH",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("attemptId", "attempt:forged"),
        ("originalSourceRoot", "/projects/forged"),
        ("laneRoot", "/projects/forged-lane"),
    ],
)
def test_acquire_rejects_self_consistent_unbound_admission_identity(
    repository_root, coordinator_factory, field, value
):
    command = coordinator_factory.acquire(**{field: value})

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_acquire_command(repository_root, command)

    assert caught.value.code == "ADMISSION_AUTHORITY_BINDING_MISMATCH"


@pytest.mark.parametrize(
    "field",
    [
        "projectExecutionKey",
        "leaseId",
        "attemptId",
        "fencingToken",
        "expectedState",
        "nextState",
        "authoritySnapshotFingerprint",
        "candidateIdentity",
        "processQuiescence",
        "lifecycleAuthorityProof",
        "reviewEvidence",
    ],
)
def test_transition_digest_binds_every_authority_field(
    repository_root, coordinator_factory, field
):
    command = coordinator_factory.transition()
    changed_authority = copy.deepcopy(command["lifecycleAuthorityProof"])
    changed_authority["assertedAt"] = "2026-08-13T12:29:01Z"
    changed_authority["proofDigest"] = _sha256(
        {
            key: value
            for key, value in changed_authority.items()
            if key != "proofDigest"
        }
    )
    review_source = coordinator_factory.transition(
        expectedState="FIXED_CANDIDATE", nextState="REVIEW_GO"
    )["reviewEvidence"]
    mutations = {
        "projectExecutionKey": "project-execution:" + "a" * 64,
        "leaseId": "lease:" + "b" * 24,
        "attemptId": "attempt:changed",
        "fencingToken": 8,
        "expectedState": "ADMITTED",
        "nextState": "REVIEW_GO",
        "authoritySnapshotFingerprint": "sha256:" + "c" * 64,
        "candidateIdentity": {
            **command["candidateIdentity"],
            "commit": "d" * 40,
        },
        "processQuiescence": {
            **command["processQuiescence"],
            "observedAt": "2026-08-13T12:30:01Z",
        },
        "lifecycleAuthorityProof": changed_authority,
        "reviewEvidence": review_source,
    }
    command[field] = mutations[field]

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_transition_command(repository_root, command)

    assert caught.value.code == "COMMAND_DIGEST_MISMATCH"


def test_transition_rejects_skipped_state_and_malformed_candidate(
    repository_root, coordinator_factory
):
    skipped = coordinator_factory.transition(nextState="REVIEW_GO")
    with pytest.raises(ControlledCoordinationError) as invalid_transition:
        normalize_transition_command(repository_root, skipped)
    assert invalid_transition.value.code == "INVALID_STATE_TRANSITION"

    malformed = coordinator_factory.transition(
        candidateIdentity={"commit": "4" * 40, "parent": "5" * 40}
    )
    with pytest.raises(ControlledCoordinationError) as invalid_candidate:
        normalize_transition_command(repository_root, malformed)
    assert invalid_candidate.value.code == "COORDINATOR_COMMAND_INVALID"


@pytest.mark.parametrize(
    ("expected_state", "next_state"),
    [
        ("ACTIVE", "FIXED_CANDIDATE"),
        ("FIXED_CANDIDATE", "REVIEW_GO"),
        ("REVIEW_GO", "QUEUED_FOR_INTEGRATION"),
        ("QUEUED_FOR_INTEGRATION", "INTEGRATING"),
        ("INTEGRATING", "CLOSED"),
        ("ACTIVE", "BLOCKED"),
        ("ACTIVE", "NO_GO"),
        ("ACTIVE", "STALE"),
        ("ACTIVE", "CANCELLED"),
    ],
)
def test_transition_accepts_declared_normal_and_exceptional_edges(
    repository_root, coordinator_factory, expected_state, next_state
):
    candidate = (
        None
        if next_state in {"BLOCKED", "NO_GO", "STALE", "CANCELLED"}
        else coordinator_factory.transition()["candidateIdentity"]
    )
    command = coordinator_factory.transition(
        expectedState=expected_state,
        nextState=next_state,
        candidateIdentity=candidate,
    )

    normalized = normalize_transition_command(repository_root, command)

    assert (normalized["expectedState"], normalized["nextState"]) == (
        expected_state,
        next_state,
    )


@pytest.mark.parametrize(
    "field",
    [
        "projectExecutionKey",
        "leaseId",
        "fencingToken",
        "beforeInventoryDigest",
        "observedPaths",
        "ephemeralPathsRemoved",
        "processQuiescence",
    ],
)
def test_observation_digest_binds_every_authority_field(
    repository_root, coordinator_factory, field
):
    command = coordinator_factory.observation()
    mutations = {
        "projectExecutionKey": "project-execution:" + "a" * 64,
        "leaseId": "lease:" + "b" * 24,
        "fencingToken": 8,
        "beforeInventoryDigest": "sha256:" + "c" * 64,
        "observedPaths": ["services/neutral-a/changed.py"],
        "ephemeralPathsRemoved": ["build/neutral-a/changed"],
        "processQuiescence": {
            **command["processQuiescence"],
            "observedAt": "2026-08-13T12:31:01Z",
        },
    }
    command[field] = mutations[field]

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_write_observation_command(repository_root, command)

    assert caught.value.code == "COMMAND_DIGEST_MISMATCH"


def test_observation_sorts_declared_path_sets_but_preserves_input(
    repository_root, coordinator_factory
):
    command = coordinator_factory.observation(
        observedPaths=["services/z.py", "services/a.py"],
        ephemeralPathsRemoved=["build/z", "build/a"],
    )
    digest_payload = copy.deepcopy(command)
    digest_payload["observedPaths"] = ["services/a.py", "services/z.py"]
    digest_payload["ephemeralPathsRemoved"] = ["build/a", "build/z"]
    command["commandDigest"] = _sha256(
        {key: value for key, value in digest_payload.items() if key != "commandDigest"}
    )
    original = copy.deepcopy(command)

    normalized = normalize_write_observation_command(repository_root, command)

    assert command == original
    assert normalized["observedPaths"] == ["services/a.py", "services/z.py"]
    assert normalized["ephemeralPathsRemoved"] == ["build/a", "build/z"]


@pytest.mark.parametrize(
    "field",
    [
        "projectExecutionKey",
        "recoveryId",
        "recoveryAuthorityId",
        "recoveryAuthorityReference",
        "recoveryAuthorityDigest",
        "recoveryAuthorityPublicKey",
        "signatureAlgorithm",
        "signatureFormat",
        "signature",
        "expectedJournalVersion",
        "processQuiescenceProofs",
        "observedWriteSet",
        "affectedLeaseDecisions",
        "replacementPlanRequired",
    ],
)
def test_recovery_digest_binds_every_authority_field(
    repository_root, coordinator_factory, field
):
    command = coordinator_factory.recovery()
    mutations = {
        "projectExecutionKey": "project-execution:" + "a" * 64,
        "recoveryId": "recovery:" + "b" * 24,
        "recoveryAuthorityId": "other-controller",
        "recoveryAuthorityReference": "authority/other.yaml",
        "recoveryAuthorityDigest": "sha256:" + "c" * 64,
        "recoveryAuthorityPublicKey": _FAKE_RECOVERY_PUBLIC_KEY.replace(
            "IG499", "IH499"
        ),
        "signatureAlgorithm": "RSA",
        "signatureFormat": "OTHER",
        "signature": _FAKE_SSHSIG + "tampered",
        "expectedJournalVersion": 12,
        "processQuiescenceProofs": [
            {
                **command["processQuiescenceProofs"][0],
                "observedAt": "2026-08-13T12:32:01Z",
            }
        ],
        "observedWriteSet": ["services/neutral-a/changed.py"],
        "affectedLeaseDecisions": [
            {
                **command["affectedLeaseDecisions"][0],
                "decision": "CANCELLED",
            }
        ],
        "replacementPlanRequired": False,
    }
    command[field] = mutations[field]

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_recovery_command(repository_root, command)

    expected = (
        "COORDINATOR_COMMAND_INVALID"
        if field
        in {
            "recoveryAuthorityId",
            "signatureAlgorithm",
            "signatureFormat",
            "replacementPlanRequired",
        }
        else "COMMAND_DIGEST_MISMATCH"
    )
    assert caught.value.code == expected


def test_recovery_normalizes_declared_sets_and_preserves_decision_members(
    repository_root, coordinator_factory
):
    base = coordinator_factory.recovery()
    proof = base["processQuiescenceProofs"][0]
    decision = base["affectedLeaseDecisions"][0]
    command = coordinator_factory.recovery(
        processQuiescenceProofs=[
            {**proof, "leaseId": "lease:" + "f" * 24},
            {**proof, "leaseId": "lease:" + "2" * 24},
        ],
        observedWriteSet=["services/z.py", "services/a.py"],
        affectedLeaseDecisions=[
            {**decision, "leaseId": "lease:" + "f" * 24},
            {**decision, "leaseId": "lease:" + "2" * 24},
        ],
    )
    digest_payload = copy.deepcopy(command)
    digest_payload["processQuiescenceProofs"] = sorted(
        digest_payload["processQuiescenceProofs"], key=lambda item: item["leaseId"]
    )
    digest_payload["observedWriteSet"] = ["services/a.py", "services/z.py"]
    digest_payload["affectedLeaseDecisions"] = sorted(
        digest_payload["affectedLeaseDecisions"], key=lambda item: item["leaseId"]
    )
    command["commandDigest"] = _sha256(
        {key: value for key, value in digest_payload.items() if key != "commandDigest"}
    )

    normalized = normalize_recovery_command(repository_root, command)

    assert normalized["observedWriteSet"] == ["services/a.py", "services/z.py"]
    assert [item["leaseId"] for item in normalized["processQuiescenceProofs"]] == [
        "lease:" + "2" * 24,
        "lease:" + "f" * 24,
    ]
    assert [item["leaseId"] for item in normalized["affectedLeaseDecisions"]] == [
        "lease:" + "2" * 24,
        "lease:" + "f" * 24,
    ]
    assert all(set(item) == {"leaseId", "decision", "reason"} for item in normalized["affectedLeaseDecisions"])


@pytest.mark.parametrize(
    ("normalizer", "builder", "field"),
    [
        (normalize_acquire_command, "acquire", "projectId"),
        (normalize_transition_command, "transition", "attemptId"),
        (normalize_write_observation_command, "observation", "leaseId"),
        (normalize_recovery_command, "recovery", "recoveryId"),
    ],
)
def test_commands_reject_empty_identifiers(
    repository_root, coordinator_factory, normalizer, builder, field
):
    command = getattr(coordinator_factory, builder)(**{field: ""})

    with pytest.raises(ControlledCoordinationError) as caught:
        normalizer(repository_root, command)

    assert caught.value.code == "COORDINATOR_COMMAND_INVALID"


@pytest.mark.parametrize(
    ("normalizer", "builder", "timestamp_path"),
    [
        (normalize_acquire_command, "acquire", ("asOf",)),
        (
            normalize_transition_command,
            "transition",
            ("processQuiescence", "observedAt"),
        ),
        (
            normalize_write_observation_command,
            "observation",
            ("processQuiescence", "observedAt"),
        ),
        (
            normalize_recovery_command,
            "recovery",
            ("processQuiescenceProofs", 0, "observedAt"),
        ),
    ],
)
def test_commands_reject_noncanonical_timestamps(
    repository_root, coordinator_factory, normalizer, builder, timestamp_path
):
    command = getattr(coordinator_factory, builder)()
    target = command
    for part in timestamp_path[:-1]:
        target = target[part]
    target[timestamp_path[-1]] = "2026-08-13 12:00:00+00:00"
    command = _with_command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        normalizer(repository_root, command)

    assert caught.value.code == "TIMESTAMP_INVALID"


@pytest.mark.parametrize(
    "action_class",
    [
        "action:database-write",
        "action:migration-apply",
        "action:destructive",
        "action:production-access",
        "action:landing",
        "action:wave-entry",
        "action:push",
        "action:release",
        "action:deploy",
    ],
)
def test_acquire_rejects_protected_action_even_when_envelope_permits_it(
    repository_root, coordinator_factory, action_class
):
    command = coordinator_factory.acquire(action_class=action_class)
    assert command["executionPlan"]["proposedAdmissions"] == []

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_acquire_command(repository_root, command)

    assert caught.value.code == "PROTECTED_ACTION_DENIED"


def test_acquire_does_not_misclassify_an_unproposed_ordinary_slice_as_protected(
    repository_root, coordinator_factory
):
    command = coordinator_factory.acquire(sliceId="slice:ordinary-but-absent")

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_acquire_command(repository_root, command)

    assert caught.value.code == "ADMISSION_AUTHORITY_BINDING_MISMATCH"


def test_exceptional_states_cannot_transition_without_recovery(
    repository_root, coordinator_factory
):
    command = coordinator_factory.transition(
        expectedState="BLOCKED",
        nextState="STALE",
        candidateIdentity=None,
    )

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_transition_command(repository_root, command)

    assert caught.value.code == "INVALID_STATE_TRANSITION"


def test_transition_requires_digest_bound_lifecycle_authority(
    repository_root, coordinator_factory
):
    command = coordinator_factory.transition()
    command.pop("lifecycleAuthorityProof")
    command = _with_command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_transition_command(repository_root, command)

    assert caught.value.code == "COORDINATOR_COMMAND_INVALID"


def test_transition_accepts_closed_ed25519_evidence_shape(
    repository_root, coordinator_factory
):
    command = coordinator_factory.transition(
        expectedState="FIXED_CANDIDATE", nextState="REVIEW_GO"
    )

    normalized = normalize_transition_command(repository_root, command)

    assert normalized["lifecycleAuthorityProof"]["authorityId"] == (
        "lifecycle-controller"
    )
    assert normalized["lifecycleAuthorityProof"]["signatureAlgorithm"] == "ED25519"
    assert normalized["lifecycleAuthorityProof"]["signatureFormat"] == (
        "OPENSSH_SSHSIG_V1"
    )
    assert normalized["reviewEvidence"]["reviewerRole"] == "deep-reviewer"
    assert normalized["reviewEvidence"]["projectExecutionKey"] == (
        normalized["projectExecutionKey"]
    )


def test_review_go_requires_candidate_bound_zero_finding_review_evidence(
    repository_root, coordinator_factory
):
    command = coordinator_factory.transition(
        expectedState="FIXED_CANDIDATE",
        nextState="REVIEW_GO",
        reviewEvidence=None,
    )

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_transition_command(repository_root, command)

    assert caught.value.code == "REVIEW_EVIDENCE_REQUIRED"


def test_transition_rejects_lifecycle_authority_proof_for_another_transition(
    repository_root, coordinator_factory
):
    command = coordinator_factory.transition()
    command["lifecycleAuthorityProof"]["nextState"] = "REVIEW_GO"
    command["lifecycleAuthorityProof"]["proofDigest"] = _sha256(
        {
            key: value
            for key, value in command["lifecycleAuthorityProof"].items()
            if key != "proofDigest"
        }
    )
    command = _with_command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_transition_command(repository_root, command)

    assert caught.value.code == "LIFECYCLE_AUTHORITY_BINDING_MISMATCH"


def test_review_go_rejects_review_evidence_for_another_candidate(
    repository_root, coordinator_factory
):
    command = coordinator_factory.transition(
        expectedState="FIXED_CANDIDATE", nextState="REVIEW_GO"
    )
    command["reviewEvidence"]["candidateIdentity"]["commit"] = "d" * 40
    command["reviewEvidence"]["evidenceDigest"] = _sha256(
        {
            key: value
            for key, value in command["reviewEvidence"].items()
            if key != "evidenceDigest"
        }
    )
    command = _with_command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_transition_command(repository_root, command)

    assert caught.value.code == "REVIEW_EVIDENCE_BINDING_MISMATCH"


def test_review_go_rejects_coordinated_candidate_and_reviewer_replacement(
    repository_root, coordinator_factory
):
    command = coordinator_factory.transition(
        expectedState="FIXED_CANDIDATE", nextState="REVIEW_GO"
    )
    forged_candidate = {
        "commit": "d" * 40,
        "parent": "e" * 40,
        "tree": "f" * 40,
    }
    command["candidateIdentity"] = forged_candidate
    evidence = command["reviewEvidence"]
    evidence["candidateIdentity"] = copy.deepcopy(forged_candidate)
    evidence["reviewerId"] = "reviewer:forged"
    evidence["reviewBindingDigest"] = _sha256(
        {
            "candidateIdentity": forged_candidate,
            "authoritySnapshotFingerprint": command[
                "authoritySnapshotFingerprint"
            ],
            "attemptId": command["attemptId"],
        }
    )
    evidence["evidenceDigest"] = _sha256(
        {key: value for key, value in evidence.items() if key != "evidenceDigest"}
    )
    command = _with_command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_transition_command(repository_root, command)

    assert caught.value.code == "LIFECYCLE_AUTHORITY_BINDING_MISMATCH"


def test_review_go_rejects_nonzero_finding_counts(
    repository_root, coordinator_factory
):
    command = coordinator_factory.transition(
        expectedState="FIXED_CANDIDATE", nextState="REVIEW_GO"
    )
    command["reviewEvidence"]["findingCounts"]["p1"] = 1
    command["reviewEvidence"]["evidenceDigest"] = _sha256(
        {
            key: value
            for key, value in command["reviewEvidence"].items()
            if key != "evidenceDigest"
        }
    )
    command = _with_command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_transition_command(repository_root, command)

    assert caught.value.code == "COORDINATOR_COMMAND_INVALID"


def test_lease_journal_and_receipt_schemas_are_closed(
    repository_root, coordinator_factory
):
    acquire = normalize_acquire_command(repository_root, coordinator_factory.acquire())
    lease = {
        "schemaVersion": "controlled-execution-lease/v1",
        "projectExecutionKey": "project-execution:" + "1" * 64,
        "leaseId": "lease:" + "2" * 24,
        "batchPlanId": acquire["batchPlanId"],
        "sliceId": acquire["sliceId"],
        "attemptId": acquire["attemptId"],
        "authoritySnapshotFingerprint": acquire["authoritySnapshotFingerprint"],
        "authorizationEnvelopeDigest": acquire["authorizationEnvelopeDigest"],
        "conflictPolicyVersion": acquire["conflictPolicyVersion"],
        "descriptorDigest": acquire["executionPlan"]["proposedAdmissions"][0][
            "descriptorDigest"
        ],
            "fullFootprint": acquire["fullFootprint"],
            "planningFootprints": [acquire["fullFootprint"]],
            "originalSourceRoot": acquire["originalSourceRoot"],
            "laneRoot": acquire["laneRoot"],
            "lanePhysicalIdentity": {
                "device": 1,
                "inode": 2,
                "type": "DIRECTORY",
            },
        "expectedLaneBase": acquire["expectedLaneBase"],
        "fencingToken": 1,
        "state": "ADMITTED",
        "candidateIdentity": None,
        "acquiredAt": acquire["asOf"],
        "lastTransitionAt": acquire["asOf"],
        "released": False,
        "recoveryStatus": "CLEAR",
    }
    receipt = {
        "schemaVersion": "controlled-coordinator-receipt/v1",
        "receiptId": "coordinator-receipt:" + "a" * 24,
        "receiptType": "ACQUIRE",
        "projectExecutionKey": lease["projectExecutionKey"],
        "previousJournalVersion": 0,
        "nextJournalVersion": 1,
        "commandDigest": acquire["commandDigest"],
        "fencingToken": 1,
        "previousState": None,
        "nextState": "ADMITTED",
        "authoritySnapshotFingerprint": acquire["authoritySnapshotFingerprint"],
        "journalDigest": "sha256:" + "b" * 64,
        "recordedAt": acquire["asOf"],
        "evidence": {"command": acquire},
    }
    journal = {
        "schemaVersion": "controlled-coordinator-journal/v1",
        "projectExecutionKey": lease["projectExecutionKey"],
        "journalVersion": 1,
        "nextFencingToken": 2,
        "recoveryState": "CLEAR",
        "recoveryEvidence": None,
        "leases": [lease],
        "receipts": [receipt],
        "integrationTransactions": [],
    }
    store = SchemaStore(repository_root)
    store.validate("core/schemas/controlled-execution-lease.schema.json", lease)
    store.validate("core/schemas/controlled-coordinator-receipt.schema.json", receipt)
    store.validate("core/schemas/controlled-coordinator-journal.schema.json", journal)

    for schema_path, value in (
        ("core/schemas/controlled-execution-lease.schema.json", lease),
        ("core/schemas/controlled-coordinator-receipt.schema.json", receipt),
        ("core/schemas/controlled-coordinator-journal.schema.json", journal),
    ):
        unknown = {**value, "surprise": True}
        with pytest.raises(SchemaValidationError):
            store.validate(schema_path, unknown)


def test_journal_requires_explicit_nullable_recovery_evidence(repository_root):
    journal = {
        "schemaVersion": "controlled-coordinator-journal/v1",
        "projectExecutionKey": "project-execution:" + "1" * 64,
        "journalVersion": 0,
        "nextFencingToken": 1,
        "recoveryState": "CLEAR",
        "leases": [],
        "receipts": [],
        "integrationTransactions": [],
    }

    with pytest.raises(SchemaValidationError):
        SchemaStore(repository_root).validate(
            "core/schemas/controlled-coordinator-journal.schema.json", journal
        )


@pytest.mark.parametrize(
    "recovery_state", ["PROJECT_WRITESET_RECOVERY", "STATE_RECOVERY_REQUIRED"]
)
def test_pending_recovery_states_require_complete_nonnull_evidence(
    repository_root, recovery_state
):
    journal = {
        "schemaVersion": "controlled-coordinator-journal/v1",
        "projectExecutionKey": "project-execution:" + "1" * 64,
        "journalVersion": 2,
        "nextFencingToken": 3,
        "recoveryState": recovery_state,
        "recoveryEvidence": None,
        "leases": [],
        "receipts": [],
        "integrationTransactions": [],
    }

    with pytest.raises(SchemaValidationError):
        SchemaStore(repository_root).validate(
            "core/schemas/controlled-coordinator-journal.schema.json", journal
        )


def test_journal_round_trips_full_quarantine_and_recovery_evidence(
    repository_root, coordinator_factory
):
    observation = normalize_write_observation_command(
        repository_root, coordinator_factory.observation()
    )
    recovery = normalize_recovery_command(
        repository_root, coordinator_factory.recovery()
    )
    revoked = [observation["leaseId"]]
    decisions = recovery["affectedLeaseDecisions"]
    observed_write_set = recovery["observedWriteSet"]
    common = {
        "schemaVersion": "controlled-coordinator-receipt/v1",
        "projectExecutionKey": observation["projectExecutionKey"],
        "fencingToken": observation["fencingToken"],
        "previousState": "ACTIVE",
        "nextState": "STALE",
        "authoritySnapshotFingerprint": "sha256:" + "3" * 64,
        "journalDigest": "sha256:" + "b" * 64,
        "recordedAt": "2026-08-13T12:33:00Z",
    }
    quarantine_receipt = {
        **common,
        "receiptId": "coordinator-receipt:" + "c" * 24,
        "receiptType": "WRITE_OBSERVATION",
        "previousJournalVersion": 11,
        "nextJournalVersion": 12,
        "commandDigest": observation["commandDigest"],
        "evidence": {
            "command": observation,
            "observedWriteSet": observed_write_set,
            "revokedLeaseIds": revoked,
            "affectedLeaseDecisions": decisions,
            "recoveryState": "PROJECT_WRITESET_RECOVERY",
        },
    }
    recovery_receipt = {
        **common,
        "receiptId": "coordinator-receipt:" + "d" * 24,
        "receiptType": "RECOVERY",
        "previousJournalVersion": 12,
        "nextJournalVersion": 13,
        "commandDigest": recovery["commandDigest"],
        "evidence": {
            "command": recovery,
            "observedWriteSet": observed_write_set,
            "revokedLeaseIds": revoked,
            "affectedLeaseDecisions": decisions,
            "recoveryState": "CLEAR",
        },
    }
    journal = {
        "schemaVersion": "controlled-coordinator-journal/v1",
        "projectExecutionKey": observation["projectExecutionKey"],
        "journalVersion": 13,
        "nextFencingToken": 9,
        "recoveryState": "CLEAR",
        "recoveryEvidence": {
            "observedWriteSet": observed_write_set,
            "revokedLeaseIds": revoked,
            "affectedLeaseDecisions": decisions,
            "quarantineCommand": observation,
            "recoveryCommand": recovery,
        },
        "leases": [],
        "receipts": [quarantine_receipt, recovery_receipt],
        "integrationTransactions": [],
    }
    replayed = json.loads(canonical_json_bytes(journal))
    store = SchemaStore(repository_root)

    store.validate(
        "core/schemas/controlled-coordinator-receipt.schema.json",
        replayed["receipts"][0],
    )
    store.validate(
        "core/schemas/controlled-coordinator-receipt.schema.json",
        replayed["receipts"][1],
    )
    store.validate("core/schemas/controlled-coordinator-journal.schema.json", replayed)
    assert replayed["recoveryEvidence"]["quarantineCommand"] == observation
    assert replayed["recoveryEvidence"]["recoveryCommand"] == recovery
    assert replayed["receipts"] == [quarantine_receipt, recovery_receipt]


def test_receipt_type_rejects_another_command_type_as_evidence(
    repository_root, coordinator_factory
):
    acquire = normalize_acquire_command(repository_root, coordinator_factory.acquire())
    transition = normalize_transition_command(
        repository_root, coordinator_factory.transition()
    )
    receipt = {
        "schemaVersion": "controlled-coordinator-receipt/v1",
        "receiptId": "coordinator-receipt:" + "e" * 24,
        "receiptType": "ACQUIRE",
        "projectExecutionKey": transition["projectExecutionKey"],
        "previousJournalVersion": 0,
        "nextJournalVersion": 1,
        "commandDigest": acquire["commandDigest"],
        "fencingToken": 1,
        "previousState": None,
        "nextState": "ADMITTED",
        "authoritySnapshotFingerprint": acquire["authoritySnapshotFingerprint"],
        "journalDigest": "sha256:" + "f" * 64,
        "recordedAt": acquire["asOf"],
        "evidence": {"command": transition},
    }

    with pytest.raises(SchemaValidationError):
        SchemaStore(repository_root).validate(
            "core/schemas/controlled-coordinator-receipt.schema.json", receipt
        )
