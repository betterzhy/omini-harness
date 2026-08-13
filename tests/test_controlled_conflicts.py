from __future__ import annotations

import copy

import pytest

from evolution_harness.controlled_conflicts import build_conflict_report
from evolution_harness.controlled_inputs import normalize_slice_descriptor
from evolution_harness.hashing import canonical_json_bytes


def _descriptor(controlled_factory, slice_id, **changes):
    defaults = {
        "sliceId": slice_id,
        "ownerSet": [f"owner:{slice_id.rsplit(':', 1)[-1]}"],
        "factFamilySet": [f"fact:{slice_id.rsplit(':', 1)[-1]}"],
        "exactWriteSet": [f"services/{slice_id.rsplit(':', 1)[-1]}"],
        "ephemeralWriteSet": [f"build/{slice_id.rsplit(':', 1)[-1]}"],
        "authorityReferences": [f"authority/{slice_id.rsplit(':', 1)[-1]}.yaml"],
    }
    defaults.update(changes)
    return controlled_factory.descriptor(**defaults)


def _report(repository_root, controlled_factory, descriptors):
    return build_conflict_report(
        repository_root,
        project_id="neutral-project",
        authority_snapshot_fingerprint="sha256:" + "9" * 64,
        conflict_policy_version="controlled-conflict-policy/v1",
        descriptors=[
            normalize_slice_descriptor(repository_root, item)
            for item in descriptors
        ],
    )


def _edge(report, left_slice_id, right_slice_id):
    return next(
        item for item in report["edges"]
        if item["leftSliceId"] == left_slice_id and item["rightSliceId"] == right_slice_id
    )


def test_disjoint_cross_owner_slices_have_distinct_clusters(repository_root, controlled_factory):
    report = _report(repository_root, controlled_factory, [
        _descriptor(controlled_factory, "slice:a"),
        _descriptor(controlled_factory, "slice:b"),
    ])
    assert report["edges"] == []
    assert [item["sliceIds"] for item in report["clusters"]] == [["slice:a"], ["slice:b"]]


@pytest.mark.parametrize(
    ("left", "right", "reason"),
    [
        ({"ownerSet": ["owner:shared"]}, {"ownerSet": ["owner:shared"]}, "SAME_OWNER"),
        ({"factFamilySet": ["fact:shared"]}, {"factFamilySet": ["fact:shared"]}, "FACT_FAMILY_OVERLAP"),
        ({"exactWriteSet": ["services/a"]}, {"exactWriteSet": ["services/a/App.java"]}, "EXACT_WRITESET_OVERLAP"),
        ({"ephemeralWriteSet": ["build/shared"]}, {"exactWriteSet": ["build/shared/output"]}, "EPHEMERAL_WRITESET_OVERLAP"),
        ({"bindingSet": ["binding:shared"]}, {"bindingSet": ["binding:shared"]}, "BINDING_OVERLAP"),
        ({"sharedArtifactSet": ["generated:index"]}, {"sharedArtifactSet": ["generated:index"]}, "SHARED_ARTIFACT_OVERLAP"),
    ],
)
def test_overlap_reason_matrix(repository_root, controlled_factory, left, right, reason):
    first = _descriptor(controlled_factory, "slice:a", **left)
    second = _descriptor(controlled_factory, "slice:b", **right)
    report = _report(repository_root, controlled_factory, [first, second])
    assert len(report["edges"]) == 1
    assert report["edges"][0]["leftSliceId"] == "slice:a"
    assert report["edges"][0]["rightSliceId"] == "slice:b"
    assert reason in report["edges"][0]["reasons"]


def test_public_contract_migration_and_global_artifact_are_serial_barriers(repository_root, controlled_factory):
    descriptors = [
        _descriptor(controlled_factory, "slice:contract", publicContractSet=["contract:public"]),
        _descriptor(controlled_factory, "slice:migration", migrationResourceSet=["migration:database"]),
        _descriptor(controlled_factory, "slice:global", sharedArtifactSet=["global:registry"]),
        _descriptor(controlled_factory, "slice:ordinary"),
    ]
    report = _report(repository_root, controlled_factory, descriptors)
    assert "PUBLIC_CONTRACT_SERIAL_BARRIER" in _edge(report, "slice:contract", "slice:ordinary")["reasons"]
    assert "MIGRATION_SERIAL_BARRIER" in _edge(report, "slice:migration", "slice:ordinary")["reasons"]
    assert "GLOBAL_SHARED_ARTIFACT_BARRIER" in _edge(report, "slice:global", "slice:ordinary")["reasons"]


def test_transitive_dependency_path_conflicts(repository_root, controlled_factory):
    report = _report(repository_root, controlled_factory, [
        _descriptor(controlled_factory, "slice:a", dependencySet=["slice:b"]),
        _descriptor(controlled_factory, "slice:b", dependencySet=["slice:c"]),
        _descriptor(controlled_factory, "slice:c"),
    ])
    assert "DEPENDENCY_PATH" in _edge(report, "slice:a", "slice:c")["reasons"]


def test_direct_and_transitive_producer_consumer_path_conflicts(repository_root, controlled_factory):
    report = _report(repository_root, controlled_factory, [
        _descriptor(
            controlled_factory,
            "slice:a",
            producerConsumerSet=[{"producer": "owner:a", "consumer": "owner:b"}],
        ),
        _descriptor(
            controlled_factory,
            "slice:b",
            producerConsumerSet=[{"producer": "owner:b", "consumer": "owner:c"}],
        ),
        _descriptor(controlled_factory, "slice:c"),
    ])
    assert "PRODUCER_CONSUMER_PATH" in _edge(report, "slice:a", "slice:b")["reasons"]
    assert "PRODUCER_CONSUMER_PATH" in _edge(report, "slice:a", "slice:c")["reasons"]


def test_writing_another_slice_authority_reference_conflicts(repository_root, controlled_factory):
    report = _report(repository_root, controlled_factory, [
        _descriptor(controlled_factory, "slice:a", exactWriteSet=["authority/slice-b.yaml"]),
        _descriptor(controlled_factory, "slice:b", authorityReferences=["authority/slice-b.yaml"]),
    ])
    assert "AUTHORITY_INPUT_WRITE" in _edge(report, "slice:a", "slice:b")["reasons"]


def test_input_order_does_not_change_report_or_ids(repository_root, controlled_factory):
    descriptors = [
        _descriptor(
            controlled_factory,
            "slice:a",
            ownerSet=["owner:z", "owner:a"],
            factFamilySet=["fact:z", "fact:a"],
            producerConsumerSet=[
                {"producer": "owner:a", "consumer": "owner:b"},
                {"producer": "owner:z", "consumer": "owner:y"},
            ],
            bindingSet=["binding:z", "binding:a"],
            exactWriteSet=["services/z", "services/a"],
            ephemeralWriteSet=["build/z", "build/a"],
            sharedArtifactSet=["generated:z", "generated:a"],
            dependencySet=["slice:c", "slice:b"],
            migrationResourceSet=["migration:z", "migration:a"],
            authorityReferences=["authority/z.yaml", "authority/a.yaml"],
        ),
        _descriptor(controlled_factory, "slice:b"),
        _descriptor(controlled_factory, "slice:c"),
    ]
    reversed_descriptors = []
    for descriptor in reversed(descriptors):
        reordered = copy.deepcopy(descriptor)
        for field in (
            "ownerSet", "factFamilySet", "publicContractSet", "producerConsumerSet", "bindingSet",
            "exactWriteSet", "ephemeralWriteSet", "sharedArtifactSet", "dependencySet",
            "migrationResourceSet", "authorityReferences",
        ):
            reordered[field] = list(reversed(reordered[field]))
        reordered = controlled_factory.descriptor(**{
            key: value for key, value in reordered.items() if key != "descriptorDigest"
        })
        reversed_descriptors.append(reordered)
    original = _report(repository_root, controlled_factory, descriptors)
    reordered = _report(repository_root, controlled_factory, reversed_descriptors)
    assert canonical_json_bytes(original) == canonical_json_bytes(reordered)
