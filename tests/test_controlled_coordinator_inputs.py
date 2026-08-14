from __future__ import annotations

import copy
from dataclasses import dataclass

import pytest

from evolution_harness.controlled_coordinator_inputs import (
    ControlledCoordinationError,
    normalize_acquire_command,
    normalize_recovery_command,
    normalize_transition_command,
    normalize_write_observation_command,
)
from evolution_harness.controlled_planner import build_provisional_execution_plan
from evolution_harness.hashing import canonical_json_bytes, sha256_bytes
from evolution_harness.schema import SchemaStore, SchemaValidationError


def _sha256(value):
    return "sha256:" + sha256_bytes(canonical_json_bytes(value))


def _with_command_digest(command):
    value = copy.deepcopy(command)
    value["commandDigest"] = _sha256(
        {key: item for key, item in value.items() if key != "commandDigest"}
    )
    return value


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
        return build_provisional_execution_plan(
            self.repository_root,
            self.controlled_factory.request(descriptor, envelope=envelope),
        )

    def acquire(self, **changes):
        bundle = self._plan_bundle()
        plan = bundle["executionPlan"]
        footprint = next(
            item
            for item in bundle["conflictReport"]["footprints"]
            if item["sliceId"] == "slice:neutral-a"
        )
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
            "executionPlan": plan,
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
            "recoveryAuthorityReference": "authority/recovery.yaml",
            "recoveryAuthorityDigest": "sha256:" + "9" * 64,
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
    mutations = {
        "projectId": "neutral-project-changed",
        "batchPlanId": "batch-plan:" + "a" * 24,
        "sliceId": "slice:changed",
        "attemptId": "attempt:changed",
        "authoritySnapshotFingerprint": "sha256:" + "a" * 64,
        "authorizationEnvelopeDigest": "sha256:" + "b" * 64,
        "conflictPolicyVersion": "controlled-conflict-policy/v2",
        "asOf": "2026-08-13T12:00:01Z",
        "executionPlan": {**command["executionPlan"], "asOf": "2026-08-13T12:00:01Z"},
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
        "executionPlan",
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
    command = coordinator_factory.acquire()
    command["fullFootprint"]["ownerSet"] = ["owner:z", "owner:a"]
    command["fullFootprint"]["producerConsumerSet"] = [
        {"producer": "owner:z", "consumer": "owner:a"},
        {"producer": "owner:a", "consumer": "owner:z"},
    ]
    command["fullFootprint"]["conflictFootprintId"] = (
        "footprint:"
        + sha256_bytes(
            canonical_json_bytes(
                    {
                        "projectId": command["projectId"],
                        "conflictPolicyVersion": command["conflictPolicyVersion"],
                        **{
                            **{
                                key: value
                                for key, value in command["fullFootprint"].items()
                                if key != "conflictFootprintId"
                            },
                        "ownerSet": ["owner:a", "owner:z"],
                        "producerConsumerSet": [
                            {"producer": "owner:a", "consumer": "owner:z"},
                            {"producer": "owner:z", "consumer": "owner:a"},
                        ],
                    },
                }
            )
        )[:24]
    )
    digest_payload = copy.deepcopy(command)
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
        ("laneRoot", "/projects//neutral-lanes/slice-neutral-a"),
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
    ],
)
def test_transition_digest_binds_every_authority_field(
    repository_root, coordinator_factory, field
):
    command = coordinator_factory.transition()
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
        "recoveryAuthorityReference",
        "recoveryAuthorityDigest",
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
        "recoveryAuthorityReference": "authority/other.yaml",
        "recoveryAuthorityDigest": "sha256:" + "c" * 64,
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
        if field == "replacementPlanRequired"
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
    protected_bundle = coordinator_factory._plan_bundle(action_class=action_class)
    assert protected_bundle["executionPlan"]["proposedAdmissions"] == []
    command = coordinator_factory.acquire(
        executionPlan=protected_bundle["executionPlan"],
        batchPlanId=protected_bundle["executionPlan"]["batchPlanId"],
        authoritySnapshotFingerprint=protected_bundle["executionPlan"][
            "authoritySnapshotFingerprint"
        ],
        authorizationEnvelopeDigest=protected_bundle["executionPlan"][
            "authorizationEnvelopeDigest"
        ],
    )

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_acquire_command(repository_root, command)

    assert caught.value.code == "PROTECTED_ACTION_DENIED"


def test_acquire_does_not_misclassify_an_unproposed_ordinary_slice_as_protected(
    repository_root, coordinator_factory
):
    command = coordinator_factory.acquire(sliceId="slice:ordinary-but-absent")

    with pytest.raises(ControlledCoordinationError) as caught:
        normalize_acquire_command(repository_root, command)

    assert caught.value.code == "EXECUTION_PLAN_BINDING_MISMATCH"


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
        "originalSourceRoot": acquire["originalSourceRoot"],
        "laneRoot": acquire["laneRoot"],
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
    }
    journal = {
        "schemaVersion": "controlled-coordinator-journal/v1",
        "projectExecutionKey": lease["projectExecutionKey"],
        "journalVersion": 1,
        "nextFencingToken": 2,
        "recoveryState": "CLEAR",
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
