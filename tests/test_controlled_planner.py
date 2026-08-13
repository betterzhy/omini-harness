from __future__ import annotations

import copy

import pytest

from evolution_harness.controlled_inputs import ControlledPlanningError
from evolution_harness.controlled_planner import (
    build_authorization_decision,
    build_provisional_execution_plan,
)
from evolution_harness.resolver import resolve_design_context
from evolution_harness.schema import SchemaStore


def _descriptor(controlled_factory, slice_id, **changes):
    suffix = slice_id.rsplit(":", 1)[-1]
    defaults = {
        "sliceId": slice_id,
        "ownerSet": [f"owner:{suffix}"],
        "factFamilySet": [f"fact:{suffix}"],
        "exactWriteSet": [f"services/{suffix}"],
        "ephemeralWriteSet": [f"build/{suffix}"],
        "authorityReferences": [f"authority/{suffix}.yaml"],
    }
    defaults.update(changes)
    return controlled_factory.descriptor(**defaults)


def _entry(items, slice_id):
    return next(item for item in items if item["sliceId"] == slice_id)


def _deep_dependency_chain(controlled_factory, size, *, cycle=False):
    descriptors = []
    for index in range(size):
        slice_id = f"slice:node-{index:04d}"
        if index == size - 1:
            dependencies = ["slice:node-0000"] if cycle else []
        else:
            dependencies = [f"slice:node-{index + 1:04d}"]
        descriptors.append(
            _descriptor(
                controlled_factory,
                slice_id,
                state="READY" if index == 0 else "CLOSED",
                dependencySet=dependencies,
            )
        )
    return descriptors


def _singleton_conflict_report(
    repository_root,
    *,
    project_id,
    authority_snapshot_fingerprint,
    conflict_policy_version,
    descriptors,
):
    del repository_root
    return {
        "schemaVersion": "controlled-conflict-report/v1",
        "projectId": project_id,
        "authoritySnapshotFingerprint": authority_snapshot_fingerprint,
        "conflictPolicyVersion": conflict_policy_version,
        "footprints": [],
        "edges": [],
        "clusters": [
            {
                "clusterId": f"conflict-cluster:{index:024x}",
                "sliceIds": [descriptor["sliceId"]],
            }
            for index, descriptor in enumerate(descriptors)
        ],
        "conflictReportId": "conflict-report:" + "f" * 24,
    }


def test_three_disjoint_ready_slices_are_proposed_in_deterministic_order(
    repository_root, controlled_factory
):
    descriptors = [
        _descriptor(controlled_factory, "slice:priority-1-b", priority=1),
        _descriptor(controlled_factory, "slice:priority-0", priority=0),
        _descriptor(controlled_factory, "slice:priority-1-a", priority=1),
    ]
    result = build_provisional_execution_plan(
        repository_root,
        controlled_factory.request(*descriptors),
    )
    assert set(result) == {"conflictReport", "authorizationDecision", "executionPlan"}
    plan = result["executionPlan"]
    assert plan["provisional"] is True
    assert plan["requiresCoordinatorRecheck"] is True
    assert [item["sliceId"] for item in plan["proposedAdmissions"]] == [
        "slice:priority-0",
        "slice:priority-1-a",
        "slice:priority-1-b",
    ]
    assert plan["batchBaseCommit"] == "a" * 40
    assert plan["contractRegistryDigest"] == "sha256:" + "2" * 64
    assert plan["authorizationEnvelopeDigest"] == result["authorizationDecision"]["envelopeDigest"]
    assert plan["conflictReportId"] == result["conflictReport"]["conflictReportId"]
    assert plan["authorizationDecisionId"] == result["authorizationDecision"]["authorizationDecisionId"]
    assert _entry(plan["proposedAdmissions"], "slice:priority-0")["exactWriteSetDigest"] == (
        "sha256:1e816e9c159217b7eb813cc4052efbc017da4dd4f46c9ef954995daed44e6129"
    )


def test_fourth_disjoint_slice_is_queued_by_project_capacity(repository_root, controlled_factory):
    descriptors = [
        _descriptor(controlled_factory, f"slice:{index}", priority=index)
        for index in range(4)
    ]
    plan = build_provisional_execution_plan(
        repository_root, controlled_factory.request(*descriptors)
    )["executionPlan"]
    assert [item["sliceId"] for item in plan["proposedAdmissions"]] == [
        "slice:0", "slice:1", "slice:2"
    ]
    assert plan["queued"] == [
        {"sliceId": "slice:3", "reasons": ["PROJECT_CAPACITY_LIMIT"]}
    ]


def test_dependency_depth_breaks_equal_priority_before_slice_id(repository_root, controlled_factory):
    descriptors = [
        _descriptor(controlled_factory, "slice:a-deep", dependencySet=["slice:closed"]),
        _descriptor(controlled_factory, "slice:z-shallow"),
        _descriptor(controlled_factory, "slice:closed", state="CLOSED"),
    ]
    envelope = controlled_factory.envelope(maxParallelLanes=1)
    plan = build_provisional_execution_plan(
        repository_root,
        controlled_factory.request(*descriptors, envelope=envelope),
    )["executionPlan"]
    assert [item["sliceId"] for item in plan["proposedAdmissions"]] == ["slice:z-shallow"]
    assert _entry(plan["queued"], "slice:a-deep")["reasons"] == ["PROJECT_CAPACITY_LIMIT"]


def test_only_one_ready_slice_per_conflict_cluster_is_proposed(repository_root, controlled_factory):
    descriptors = [
        _descriptor(controlled_factory, "slice:lower", ownerSet=["owner:shared"], priority=2),
        _descriptor(controlled_factory, "slice:higher", ownerSet=["owner:shared"], priority=0),
    ]
    plan = build_provisional_execution_plan(
        repository_root, controlled_factory.request(*descriptors)
    )["executionPlan"]
    assert [item["sliceId"] for item in plan["proposedAdmissions"]] == ["slice:higher"]
    assert plan["queued"] == [
        {"sliceId": "slice:lower", "reasons": ["CONFLICT_CLUSTER_BUSY"]}
    ]


def test_open_dependency_blocks_dependent_slice(repository_root, controlled_factory):
    dependency = _descriptor(controlled_factory, "slice:dependency", state="ACTIVE")
    dependent = _descriptor(
        controlled_factory, "slice:dependent", dependencySet=["slice:dependency"]
    )
    plan = build_provisional_execution_plan(
        repository_root, controlled_factory.request(dependency, dependent)
    )["executionPlan"]
    assert _entry(plan["blocked"], "slice:dependent") == {
        "sliceId": "slice:dependent",
        "reasons": ["DEPENDENCY_NOT_CLOSED"],
    }


def test_unknown_dependency_fails_closed(repository_root, controlled_factory):
    descriptor = _descriptor(
        controlled_factory, "slice:a", dependencySet=["slice:absent"]
    )
    with pytest.raises(ControlledPlanningError) as caught:
        build_provisional_execution_plan(repository_root, controlled_factory.request(descriptor))
    assert caught.value.code == "UNKNOWN_DEPENDENCY"


def test_dependency_cycle_fails_closed(repository_root, controlled_factory):
    descriptors = [
        _descriptor(controlled_factory, "slice:a", dependencySet=["slice:b"]),
        _descriptor(controlled_factory, "slice:b", dependencySet=["slice:a"]),
    ]
    with pytest.raises(ControlledPlanningError) as caught:
        build_provisional_execution_plan(repository_root, controlled_factory.request(*descriptors))
    assert caught.value.code == "DEPENDENCY_CYCLE"


def test_1100_node_dependency_chain_has_a_deterministic_provisional_outcome(
    repository_root, controlled_factory, monkeypatch
):
    descriptors = _deep_dependency_chain(controlled_factory, 1100)
    # The conflict contract intentionally projects every transitive dependency
    # edge. Isolate that quadratic output so this regression measures the
    # planner's deep traversal and public plan result.
    monkeypatch.setattr(
        "evolution_harness.controlled_planner.build_conflict_report",
        _singleton_conflict_report,
    )

    plan = build_provisional_execution_plan(
        repository_root,
        controlled_factory.request(*descriptors),
    )["executionPlan"]

    assert [item["sliceId"] for item in plan["proposedAdmissions"]] == [
        "slice:node-0000"
    ]
    assert plan["queued"] == []
    assert len(plan["blocked"]) == 1099


def test_1100_node_dependency_cycle_fails_closed_without_recursion_error(
    repository_root, controlled_factory
):
    descriptors = _deep_dependency_chain(controlled_factory, 1100, cycle=True)

    with pytest.raises(ControlledPlanningError) as caught:
        build_provisional_execution_plan(
            repository_root,
            controlled_factory.request(*descriptors),
        )

    assert caught.value.code == "DEPENDENCY_CYCLE"


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
def test_protected_actions_are_hard_denied_even_when_the_envelope_permits_them(
    repository_root, controlled_factory, action_class
):
    descriptor = _descriptor(
        controlled_factory,
        "slice:protected",
        authorizationClass=action_class,
    )
    envelope = controlled_factory.envelope(
        permittedActionClasses=[action_class],
        deniedActions=[],
    )

    result = build_provisional_execution_plan(
        repository_root,
        controlled_factory.request(descriptor, envelope=envelope),
    )

    expected_rejection = {
        "sliceId": "slice:protected",
        "reasons": ["ACTION_EXPLICITLY_DENIED"],
    }
    assert result["authorizationDecision"]["gate"] == "PASS"
    assert result["authorizationDecision"]["decisions"] == [
        {**expected_rejection, "result": "REJECT"}
    ]
    assert result["executionPlan"]["proposedAdmissions"] == []
    assert result["executionPlan"]["rejected"] == [expected_rejection]


@pytest.mark.parametrize(
    ("as_of", "reason"),
    [
        ("2026-08-12T23:59:59Z", "ENVELOPE_NOT_YET_VALID"),
        ("2026-08-14T00:00:00Z", "ENVELOPE_EXPIRED"),
    ],
)
def test_expired_or_not_yet_valid_envelope_proposes_nothing(
    repository_root, controlled_factory, as_of, reason
):
    descriptor = _descriptor(controlled_factory, "slice:a")
    result = build_provisional_execution_plan(
        repository_root,
        controlled_factory.request(descriptor, asOf=as_of),
    )
    assert result["authorizationDecision"]["gate"] == "NO_GO"
    assert result["executionPlan"]["proposedAdmissions"] == []
    assert result["authorizationDecision"]["decisions"] == [
        {"sliceId": "slice:a", "result": "REJECT", "reasons": [reason]}
    ]


@pytest.mark.parametrize(
    ("descriptor_changes", "envelope_changes", "reason"),
    [
        ({"portfolioId": "portfolio:other"}, {}, "PORTFOLIO_NOT_PERMITTED"),
        ({"deliveryTrackId": "track:other"}, {}, "DELIVERY_TRACK_NOT_PERMITTED"),
        ({"sliceClass": "class:other"}, {}, "SLICE_CLASS_NOT_PERMITTED"),
        ({"authorizationClass": "action:other"}, {}, "ACTION_CLASS_NOT_PERMITTED"),
        (
            {"authorizationClass": "action:denied"},
            {
                "permittedActionClasses": ["action:denied", "action:ordinary-development"],
                "deniedActions": ["action:denied"],
            },
            "ACTION_EXPLICITLY_DENIED",
        ),
        ({"exactWriteSet": ["outside/source"]}, {}, "WRITESET_OUTSIDE_PREFIX"),
        ({"ephemeralWriteSet": ["outside/build"]}, {}, "WRITESET_OUTSIDE_PREFIX"),
    ],
)
def test_track_class_action_denial_and_path_prefix_denials_are_explained(
    repository_root,
    controlled_factory,
    descriptor_changes,
    envelope_changes,
    reason,
):
    descriptor = _descriptor(controlled_factory, "slice:a", **descriptor_changes)
    envelope = controlled_factory.envelope(**envelope_changes)
    decision = build_authorization_decision(
        repository_root,
        controlled_factory.request(descriptor, envelope=envelope),
    )
    assert decision["decisions"] == [
        {"sliceId": "slice:a", "result": "REJECT", "reasons": [reason]}
    ]


def test_every_output_validates_against_its_schema(repository_root, controlled_factory):
    result = build_provisional_execution_plan(
        repository_root,
        controlled_factory.request(_descriptor(controlled_factory, "slice:a")),
    )
    store = SchemaStore(repository_root)
    store.validate("core/schemas/controlled-conflict-report.schema.json", result["conflictReport"])
    store.validate(
        "core/schemas/controlled-authorization-decision.schema.json",
        result["authorizationDecision"],
    )
    store.validate("core/schemas/controlled-execution-plan.schema.json", result["executionPlan"])


def test_execution_requirements_preserve_envelope_and_slice_obligations(
    repository_root, controlled_factory
):
    descriptors = [
        _descriptor(
            controlled_factory,
            "slice:b",
            requiredGates=["compile", "integration"],
            reviewPolicy={"reviewerRole": "reviewer-b", "minimumVerdict": "GO_ZERO_FINDINGS"},
        ),
        _descriptor(
            controlled_factory,
            "slice:a",
            requiredGates=["lint", "compile"],
            reviewPolicy={"reviewerRole": "reviewer-a", "minimumVerdict": "GO_ZERO_FINDINGS"},
        ),
    ]
    envelope = controlled_factory.envelope(
        requiredTests=["contract", "pytest"],
        requiredGates=["authority", "lint"],
        requiredReviewers=["gatekeeper"],
    )
    requirements = build_provisional_execution_plan(
        repository_root,
        controlled_factory.request(*descriptors, envelope=envelope),
    )["executionPlan"]["executionRequirements"]
    assert requirements == {
        "requiredTests": ["contract", "pytest"],
        "requiredGates": ["authority", "lint", "compile", "integration"],
        "requiredReviewers": ["gatekeeper", "reviewer-a", "reviewer-b"],
        "minimumReviewVerdict": "GO_ZERO_FINDINGS",
        "sliceRequirements": [
            {
                "sliceId": "slice:a",
                "requiredGates": ["lint", "compile"],
                "reviewPolicy": {
                    "reviewerRole": "reviewer-a",
                    "minimumVerdict": "GO_ZERO_FINDINGS",
                },
            },
            {
                "sliceId": "slice:b",
                "requiredGates": ["compile", "integration"],
                "reviewPolicy": {
                    "reviewerRole": "reviewer-b",
                    "minimumVerdict": "GO_ZERO_FINDINGS",
                },
            },
        ],
    }


def test_stop_conditions_are_preserved_as_mandatory_recheck_inputs(
    repository_root, controlled_factory
):
    envelope = controlled_factory.envelope(
        stopConditions=["z-authority-drift", "a-gate-failure"]
    )
    plan = build_provisional_execution_plan(
        repository_root,
        controlled_factory.request(
            _descriptor(controlled_factory, "slice:a"), envelope=envelope
        ),
    )["executionPlan"]
    assert plan["mandatoryStopConditions"] == ["a-gate-failure", "z-authority-drift"]
    assert plan["provisional"] is True
    assert plan["requiresCoordinatorRecheck"] is True


def test_shuffled_equivalent_request_produces_identical_ids(repository_root, controlled_factory):
    descriptors = [
        _descriptor(
            controlled_factory,
            "slice:a",
            ownerSet=["owner:z", "owner:a"],
            exactWriteSet=["services/z", "services/a"],
            requiredGates=["unit", "integration"],
        ),
        _descriptor(controlled_factory, "slice:b"),
    ]
    shuffled = []
    for descriptor in reversed(descriptors):
        changed = copy.deepcopy(descriptor)
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
        ):
            changed[field] = list(reversed(changed[field]))
        shuffled.append(
            controlled_factory.descriptor(
                **{key: value for key, value in changed.items() if key != "descriptorDigest"}
            )
        )
    original = build_provisional_execution_plan(
        repository_root, controlled_factory.request(*descriptors)
    )
    reordered = build_provisional_execution_plan(
        repository_root, controlled_factory.request(*shuffled)
    )
    assert original["conflictReport"]["conflictReportId"] == reordered["conflictReport"]["conflictReportId"]
    assert original["authorizationDecision"]["authorizationDecisionId"] == reordered["authorizationDecision"]["authorizationDecisionId"]
    assert original["executionPlan"]["batchPlanId"] == reordered["executionPlan"]["batchPlanId"]


def test_as_of_and_envelope_are_bound_to_decision_and_plan_identity(
    repository_root, controlled_factory
):
    descriptor = _descriptor(controlled_factory, "slice:a")
    original = build_provisional_execution_plan(
        repository_root, controlled_factory.request(descriptor)
    )
    later = build_provisional_execution_plan(
        repository_root,
        controlled_factory.request(descriptor, asOf="2026-08-13T12:00:01Z"),
    )
    changed_envelope = controlled_factory.envelope(requiredTests=["contract", "pytest"])
    rebound = build_provisional_execution_plan(
        repository_root,
        controlled_factory.request(descriptor, envelope=changed_envelope),
    )
    assert original["authorizationDecision"]["authorizationDecisionId"] != later["authorizationDecision"]["authorizationDecisionId"]
    assert original["executionPlan"]["batchPlanId"] != later["executionPlan"]["batchPlanId"]
    assert original["conflictReport"]["conflictReportId"] == later["conflictReport"]["conflictReportId"]
    assert original["authorizationDecision"]["authorizationDecisionId"] != rebound["authorizationDecision"]["authorizationDecisionId"]
    assert original["executionPlan"]["batchPlanId"] != rebound["executionPlan"]["batchPlanId"]


def test_existing_serial_resolution_is_unchanged_without_a_planning_request(repository_root):
    result = resolve_design_context(
        repository_root,
        repository_root / "examples/project-fixture",
        intent="architecture-review",
        topic="resolver-mvp",
        requested_output="review findings",
        runtime="CHATGPT",
    )
    assert [item["id"] for item in result["selectedCapabilities"]] == [
        "framework:agent-design:authority-analysis",
        "framework:agent-design:lifecycle-analysis",
        "principle:agent-design:closure-requires-authority",
        "principle:agent-design:project-truth-over-generic-guidance",
        "skill:agent-design:architecture-review",
        "skill:agent-design:design-closure-assessment",
    ]
