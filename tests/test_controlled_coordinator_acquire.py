from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from evolution_harness.authority import build_authority_snapshot
from evolution_harness.controlled_coordinator import (
    acquire_lane_lease,
    resolve_project_execution_identity,
)
from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError
from evolution_harness.controlled_inputs import ControlledPlanningError, dependency_graph_digest
from evolution_harness.hashing import canonical_json_bytes, sha256_bytes
from evolution_harness.controlled_planner import build_provisional_execution_plan
from evolution_harness.coordinator_state import CoordinatorStateStore
from evolution_harness.schema import SchemaStore, SchemaValidationError


def _sha256(value):
    return "sha256:" + sha256_bytes(canonical_json_bytes(value))


def _command_digest(command):
    command["commandDigest"] = _sha256(
        {key: value for key, value in command.items() if key != "commandDigest"}
    )
    return command


def _coordinator_snapshot(factory, command):
    journal = factory.journal()
    return {
        "schemaVersion": "controlled-coordinator-snapshot/v1",
        "projectId": command["projectId"],
        "projectExecutionKey": journal["projectExecutionKey"],
        "baseBatchPlanId": command["batchPlanId"],
        "journalVersion": journal["journalVersion"],
        "journalDigest": journal["receipts"][-1]["journalDigest"],
        "recoveryState": journal["recoveryState"],
        "authorizationEnvelopeDigest": command["authorizationEnvelopeDigest"],
        "conflictPolicyVersion": command["conflictPolicyVersion"],
        "expectedLaneBase": command["expectedLaneBase"],
        "journal": journal,
    }


def _git(path: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *argv],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _fixture_descriptor(controlled_factory, suffix: str):
    changes = {}
    if suffix == "middle":
        changes["producerConsumerSet"] = [
            {"producer": "owner:neutral-active-a", "consumer": "owner:neutral-middle"},
            {"producer": "owner:neutral-middle", "consumer": "owner:neutral-target"},
        ]
    return controlled_factory.descriptor(
        sliceId=f"slice:neutral-{suffix}",
        ownerSet=[f"owner:neutral-{suffix}"],
        factFamilySet=[f"fact:neutral-{suffix}"],
        exactWriteSet=[f"services/neutral-{suffix}"],
        ephemeralWriteSet=[f"build/neutral-{suffix}"],
        authorityReferences=["status.md"],
        **changes,
    )


def _populate_controlled_authority(
    destination: Path, controlled_factory, *, development_authorized: bool = True
) -> None:
    if development_authorized:
        (destination / "status.md").write_text(
            "# External Project Status\n\n"
            "ProjectStage = DELIVERY\n"
            "DevelopmentAuthorization = YES_TASK3_TEST\n",
            encoding="utf-8",
        )
    issuer_digest = "sha256:" + sha256_bytes(
        (destination / "coordinator-issuer.yaml").read_bytes()
    )
    descriptors = [
        _fixture_descriptor(controlled_factory, suffix)
        for suffix in ("a", "b", "c", "active-a", "middle", "target")
    ]
    contract_digest = "sha256:" + "2" * 64
    envelope_digests = []
    for max_lanes in (1, 2, 3):
        for required_tests in (["pytest"], ["pytest", "changed-envelope"]):
            envelope = controlled_factory.envelope(
                projectId="neutral-shadow",
                issuerId="coordinator-issuer",
                issuerAuthorityReference="coordinator-issuer.yaml",
                issuerAuthorityDigest=issuer_digest,
                maxParallelLanes=max_lanes,
                deniedActions=[],
                requiredTests=required_tests,
            )
            for field in (
                "permittedDeliveryTracks",
                "permittedSliceClasses",
                "permittedPathPrefixes",
                "permittedActionClasses",
                "requiredTests",
                "requiredReviewers",
                "deniedActions",
                "stopConditions",
            ):
                envelope[field] = sorted(envelope[field])
            envelope_digests.append(envelope["envelopeDigest"])
    source = destination.absolute()
    isolation = source.parent / f"{source.name}-lanes"
    lane_paths = [
        isolation / name
        for name in (
            "slice-neutral-a",
            "slice-neutral-b",
            "slice-neutral-c",
            "slice-neutral-active-a",
            "slice-neutral-middle",
            "slice-neutral-target",
            "shared",
            "physical-alias",
        )
    ] + [source.parent / "unapproved" / "lane"]
    bindings = [
        {
            "projectId": "neutral-shadow",
            "sliceId": descriptor["sliceId"],
            "attemptId": f"attempt:neutral-{attempt}",
            "originalSourceRoot": str(source),
            "laneRoot": str(lane),
        }
        for descriptor in descriptors
        for attempt in ("a", "b", "c", "active-a", "middle", "target")
        for lane in lane_paths
    ]
    manifest = {
        "schemaVersion": "controlled-planning-authority/v1",
        "planning": {
            "mode": ["CONTROLLED_PARALLEL"],
            "contractRegistryDigest": [contract_digest],
            "dependencyGraphDigest": sorted({
                *(dependency_graph_digest([item]) for item in descriptors),
                dependency_graph_digest([descriptors[3], descriptors[4]]),
            }),
            "authorizationEnvelopeDigest": sorted(set(envelope_digests)),
            "sliceDescriptorDigests": sorted([
                *[[item["descriptorDigest"]] for item in descriptors],
                sorted([descriptors[3]["descriptorDigest"], descriptors[4]["descriptorDigest"]]),
            ]),
            "conflictPolicyVersion": ["controlled-conflict-policy/v1"],
        },
        "admission": {
            "bindings": sorted(
                bindings,
                key=lambda item: (
                    item["sliceId"], item["attemptId"], item["laneRoot"]
                ),
            )
        },
    }
    (destination / "controlled-planning.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )


def _committed_source(
    repository_root: Path,
    destination: Path,
    controlled_factory,
    *,
    development_authorized: bool = True,
) -> Path:
    shutil.copytree(repository_root / "examples/external-project-source", destination)
    _populate_controlled_authority(
        destination,
        controlled_factory,
        development_authorized=development_authorized,
    )
    _git(destination, "init", "-q")
    _git(destination, "config", "user.name", "Coordinator Test")
    _git(destination, "config", "user.email", "coordinator@example.test")
    _git(destination, "add", ".")
    _git(destination, "commit", "-qm", "fixture")
    return destination


@dataclass
class AcquisitionFactory:
    repository_root: Path
    source_root: Path
    controlled_factory: object

    @property
    def isolation_root(self) -> Path:
        return self.source_root.parent / f"{self.source_root.name}-lanes"

    def acquire(
        self,
        *,
        slice_id: str = "slice:neutral-a",
        attempt_id: str = "attempt:neutral-a",
        owner: str = "owner:neutral-a",
        exact_write_set: str = "services/neutral-a",
        lane_name: str | None = None,
        max_parallel_lanes: int = 3,
        as_of: str = "2026-08-13T12:00:00Z",
        envelope_changes: dict | None = None,
        snapshot_changes: dict | None = None,
        lane_root: Path | None = None,
        additional_descriptors: list[dict] | None = None,
        create_lane: bool = True,
    ) -> dict:
        suffix = slice_id.removeprefix("slice:neutral-")
        descriptor = _fixture_descriptor(self.controlled_factory, suffix)
        if descriptor["ownerSet"] != [owner] or descriptor["exactWriteSet"] != [exact_write_set]:
            descriptor = self.controlled_factory.descriptor(
                sliceId=slice_id,
                ownerSet=[owner],
                factFamilySet=[f"fact:{slice_id.removeprefix('slice:')}"],
                exactWriteSet=[exact_write_set],
                ephemeralWriteSet=[f"build/{slice_id.removeprefix('slice:')}"],
                authorityReferences=["status.md"],
            )
        request_descriptors = [descriptor, *(additional_descriptors or [])]
        live = build_authority_snapshot(
            self.repository_root,
            self.repository_root / "integrations/neutral-shadow",
            self.source_root,
        )
        issuer = next(
            item for item in live["authorities"] if item["id"] == "coordinator-issuer"
        )
        manifest = next(
            item
            for item in live["authorities"]
            if item["id"] == "controlled-planning-manifest"
        )
        envelope = self.controlled_factory.envelope(
            projectId="neutral-shadow",
            issuerId=issuer["id"],
            issuerAuthorityReference=issuer["path"],
            issuerAuthorityDigest="sha256:" + issuer["sha256"],
            maxParallelLanes=max_parallel_lanes,
            deniedActions=[],
            **(envelope_changes or {}),
        )
        for field in (
            "permittedDeliveryTracks",
            "permittedSliceClasses",
            "permittedPathPrefixes",
            "permittedActionClasses",
            "requiredTests",
            "requiredReviewers",
            "deniedActions",
            "stopConditions",
        ):
            envelope[field] = sorted(envelope[field])
        source = self.source_root.absolute()
        selected_lane_root = (
            Path(lane_root)
            if lane_root is not None
            else self.isolation_root / (lane_name or slice_id.replace(":", "-"))
        ).absolute()
        if create_lane:
            selected_lane_root.mkdir(parents=True, exist_ok=True)
        binding = {
            "projectId": "neutral-shadow",
            "sliceId": slice_id,
            "attemptId": attempt_id,
            "originalSourceRoot": str(source),
            "laneRoot": str(selected_lane_root),
        }
        request = self.controlled_factory.request(*request_descriptors, envelope=envelope)
        request.update(
            {
                "projectId": "neutral-shadow",
                "batchBaseCommit": live["sourceRevision"]["head"],
                "dependencyGraphDigest": dependency_graph_digest(request_descriptors),
                "asOf": as_of,
            }
        )
        snapshot = copy.deepcopy(live)
        snapshot.update(copy.deepcopy(snapshot_changes or {}))
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
        request["authoritySnapshot"] = copy.deepcopy(snapshot)
        bundle = build_provisional_execution_plan(self.repository_root, request)
        plan = bundle["executionPlan"]
        footprint = next(
            item
            for item in bundle["conflictReport"]["footprints"]
            if item["sliceId"] == slice_id
        )
        proof = {
            "factId": "controlled_coordination.admission.bindings",
            "manifestAuthorityId": manifest["id"],
            "manifestAuthorityReference": manifest["path"],
            "manifestAuthorityDigest": "sha256:" + manifest["sha256"],
            "binding": binding,
        }
        proof["proofDigest"] = _sha256(proof)
        return _command_digest(
            {
                "schemaVersion": "controlled-coordinator-acquire-command/v1",
                "projectId": plan["projectId"],
                "batchPlanId": plan["batchPlanId"],
                "sliceId": slice_id,
                "attemptId": attempt_id,
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
                "authoritySnapshot": snapshot,
                "admissionAuthorityProof": proof,
                "fullFootprint": footprint,
                "originalSourceRoot": str(source),
                "laneRoot": str(selected_lane_root),
                "expectedLaneBase": plan["batchBaseCommit"],
            }
        )

    def journal(self) -> dict:
        identity = resolve_project_execution_identity(
            self.repository_root, self.source_root
        )
        with CoordinatorStateStore.open(identity) as store:
            value = store.read_journal()
        assert value is not None
        return value


@pytest.fixture
def acquisition_factory(
    tmp_path, monkeypatch, repository_root, controlled_factory
):
    monkeypatch.setenv(
        "AGENT_EVOLUTION_COORDINATOR_ROOT", str(tmp_path / "coordinator-state")
    )
    source = _committed_source(
        repository_root, tmp_path / "external-project", controlled_factory
    )
    return AcquisitionFactory(repository_root, source, controlled_factory)


def test_execution_plan_schema_accepts_active_lease_conflict(
    repository_root, controlled_factory
):
    descriptor = controlled_factory.descriptor()
    plan = build_provisional_execution_plan(
        repository_root,
        controlled_factory.request(descriptor),
    )["executionPlan"]
    plan["proposedAdmissions"] = []
    plan["queued"] = [
        {"sliceId": descriptor["sliceId"], "reasons": ["ACTIVE_LEASE_CONFLICT"]}
    ]

    SchemaStore(repository_root).validate(
        "core/schemas/controlled-execution-plan.schema.json", plan
    )


def test_project_identity_collapses_path_aliases_and_separates_inodes(
    acquisition_factory, tmp_path
):
    factory = acquisition_factory
    alias = factory.source_root / ".." / factory.source_root.name
    same = resolve_project_execution_identity(factory.repository_root, alias)
    direct = resolve_project_execution_identity(
        factory.repository_root, factory.source_root
    )
    other = _committed_source(
        factory.repository_root, tmp_path / "other-project", factory.controlled_factory
    )
    distinct = resolve_project_execution_identity(factory.repository_root, other)

    assert same == direct
    assert distinct["projectExecutionKey"] != direct["projectExecutionKey"]
    assert direct["sourceDevice"] == os.lstat(factory.source_root).st_dev
    assert direct["sourceInode"] == os.lstat(factory.source_root).st_ino
    assert direct["sourceType"] == "DIRECTORY"


def test_acquire_persists_fenced_lease_and_same_command_replays(
    acquisition_factory
):
    command = acquisition_factory.acquire()

    first = acquire_lane_lease(
        acquisition_factory.repository_root,
        acquisition_factory.source_root,
        command,
    )
    replay = acquire_lane_lease(
        acquisition_factory.repository_root,
        acquisition_factory.source_root,
        copy.deepcopy(command),
    )
    journal = acquisition_factory.journal()

    assert first == replay
    assert first["fencingToken"] == 1
    assert first["state"] == "ADMITTED"
    assert first["lanePhysicalIdentity"] == {
        "device": os.lstat(command["laneRoot"]).st_dev,
        "inode": os.lstat(command["laneRoot"]).st_ino,
        "type": "DIRECTORY",
    }
    assert journal["journalVersion"] == 1
    assert journal["nextFencingToken"] == 2
    assert journal["leases"] == [first]
    assert journal["receipts"][0]["receiptType"] == "ACQUIRE"
    digest_payload = copy.deepcopy(journal)
    digest_payload["receipts"][0]["journalDigest"] = "sha256:" + "0" * 64
    assert journal["receipts"][0]["journalDigest"] == _sha256(digest_payload)


def test_cross_plan_same_owner_is_serialized(acquisition_factory):
    first = acquisition_factory.acquire(as_of="2026-08-13T12:00:00Z")
    second = acquisition_factory.acquire(
        attempt_id="attempt:neutral-b",
        as_of="2026-08-13T12:00:01Z",
        lane_name="slice-neutral-b",
    )
    acquire_lane_lease(
        acquisition_factory.repository_root, acquisition_factory.source_root, first
    )

    with pytest.raises(ControlledCoordinationError) as caught:
        acquire_lane_lease(
            acquisition_factory.repository_root,
            acquisition_factory.source_root,
            second,
        )

    assert first["batchPlanId"] != second["batchPlanId"]
    assert caught.value.code == "ACTIVE_FOOTPRINT_CONFLICT"


def test_cross_plan_transitive_owner_graph_is_serialized(acquisition_factory):
    middle = _fixture_descriptor(acquisition_factory.controlled_factory, "middle")
    active = acquisition_factory.acquire(
        slice_id="slice:neutral-active-a",
        attempt_id="attempt:neutral-active-a",
        owner="owner:neutral-active-a",
        exact_write_set="services/neutral-active-a",
        lane_name="slice-neutral-active-a",
        additional_descriptors=[middle],
    )
    target = acquisition_factory.acquire(
        slice_id="slice:neutral-target",
        attempt_id="attempt:neutral-target",
        owner="owner:neutral-target",
        exact_write_set="services/neutral-target",
        lane_name="slice-neutral-target",
    )
    acquire_lane_lease(
        acquisition_factory.repository_root, acquisition_factory.source_root, active
    )
    snapshot = _coordinator_snapshot(acquisition_factory, target)
    projected = build_provisional_execution_plan(
        acquisition_factory.repository_root,
        target["planningRequest"],
        coordinator_snapshot=snapshot,
    )

    assert projected["coordinatorProjection"]["queued"] == [
        {
            "sliceId": "slice:neutral-target",
            "reasons": ["ACTIVE_LEASE_CONFLICT"],
        }
    ]

    with pytest.raises(ControlledCoordinationError) as caught:
        acquire_lane_lease(
            acquisition_factory.repository_root,
            acquisition_factory.source_root,
            target,
        )

    assert caught.value.code == "ACTIVE_FOOTPRINT_CONFLICT"


def test_cross_plan_capacity_is_project_wide(acquisition_factory):
    commands = [
        acquisition_factory.acquire(
            slice_id=f"slice:neutral-{suffix}",
            attempt_id=f"attempt:neutral-{suffix}",
            owner=f"owner:neutral-{suffix}",
            exact_write_set=f"services/neutral-{suffix}",
            lane_name=f"slice-neutral-{suffix}",
            max_parallel_lanes=2,
            as_of=f"2026-08-13T12:00:0{index}Z",
        )
        for index, suffix in enumerate(("a", "b", "c"))
    ]
    first = acquire_lane_lease(
        acquisition_factory.repository_root, acquisition_factory.source_root, commands[0]
    )
    second = acquire_lane_lease(
        acquisition_factory.repository_root, acquisition_factory.source_root, commands[1]
    )

    with pytest.raises(ControlledCoordinationError) as caught:
        acquire_lane_lease(
            acquisition_factory.repository_root,
            acquisition_factory.source_root,
            commands[2],
        )

    assert len({item["batchPlanId"] for item in commands}) == 3
    assert [first["fencingToken"], second["fencingToken"]] == [1, 2]
    assert caught.value.code == "PROJECT_CAPACITY_LIMIT"


def test_disjoint_projects_acquire_independently(
    acquisition_factory, tmp_path, controlled_factory
):
    other_source = _committed_source(
        acquisition_factory.repository_root,
        tmp_path / "other-project",
        controlled_factory,
    )
    other = AcquisitionFactory(
        acquisition_factory.repository_root, other_source, controlled_factory
    )

    first = acquire_lane_lease(
        acquisition_factory.repository_root,
        acquisition_factory.source_root,
        acquisition_factory.acquire(),
    )
    second = acquire_lane_lease(
        other.repository_root, other.source_root, other.acquire()
    )

    assert first["projectExecutionKey"] != second["projectExecutionKey"]
    assert first["fencingToken"] == second["fencingToken"] == 1


def test_same_lane_root_is_rejected_even_for_disjoint_footprints(acquisition_factory):
    lane = acquisition_factory.isolation_root / "shared"
    first = acquisition_factory.acquire(lane_root=lane)
    second = acquisition_factory.acquire(
        slice_id="slice:neutral-b",
        attempt_id="attempt:neutral-b",
        owner="owner:neutral-b",
        exact_write_set="services/neutral-b",
        lane_root=lane,
    )
    acquire_lane_lease(
        acquisition_factory.repository_root, acquisition_factory.source_root, first
    )

    with pytest.raises(ControlledCoordinationError) as caught:
        acquire_lane_lease(
            acquisition_factory.repository_root,
            acquisition_factory.source_root,
            second,
        )

    assert caught.value.code == "LANE_ROOT_CONFLICT"


def test_lane_root_must_stay_below_project_isolation_root(acquisition_factory):
    command = acquisition_factory.acquire(
        lane_root=acquisition_factory.source_root.parent / "unapproved" / "lane"
    )

    with pytest.raises(ControlledCoordinationError) as caught:
        acquire_lane_lease(
            acquisition_factory.repository_root,
            acquisition_factory.source_root,
            command,
        )

    assert caught.value.code == "LANE_ROOT_OUTSIDE_ISOLATION"


@pytest.mark.parametrize("unsafe", ["missing", "symlink"])
def test_lane_root_must_be_existing_no_follow_directory(
    acquisition_factory, unsafe
):
    lane = acquisition_factory.isolation_root / "physical-alias"
    if unsafe == "symlink":
        target = acquisition_factory.isolation_root / "slice-neutral-c"
        target.mkdir(parents=True, exist_ok=True)
        lane.symlink_to(target, target_is_directory=True)
    command = acquisition_factory.acquire(lane_root=lane, create_lane=False)

    with pytest.raises(ControlledCoordinationError) as caught:
        acquire_lane_lease(
            acquisition_factory.repository_root,
            acquisition_factory.source_root,
            command,
        )

    assert caught.value.code == "LANE_ROOT_UNSAFE"


def test_changed_envelope_is_rejected_while_a_lease_is_nonterminal(
    acquisition_factory
):
    acquire_lane_lease(
        acquisition_factory.repository_root,
        acquisition_factory.source_root,
        acquisition_factory.acquire(),
    )
    changed = acquisition_factory.acquire(
        slice_id="slice:neutral-b",
        attempt_id="attempt:neutral-b",
        owner="owner:neutral-b",
        exact_write_set="services/neutral-b",
        lane_name="slice-neutral-b",
        envelope_changes={"requiredTests": ["pytest", "changed-envelope"]},
    )

    with pytest.raises(ControlledCoordinationError) as caught:
        acquire_lane_lease(
            acquisition_factory.repository_root,
            acquisition_factory.source_root,
            changed,
        )

    assert caught.value.code == "AUTHORIZATION_ENVELOPE_CHANGED"


def test_changed_policy_and_snapshot_are_rejected(acquisition_factory):
    policy = acquisition_factory.acquire()
    policy["conflictPolicyVersion"] = "controlled-conflict-policy/v2"
    _command_digest(policy)
    with pytest.raises(ControlledCoordinationError) as changed_policy:
        acquire_lane_lease(
            acquisition_factory.repository_root,
            acquisition_factory.source_root,
            policy,
        )
    assert changed_policy.value.code == "COORDINATOR_COMMAND_INVALID"

    snapshot = acquisition_factory.acquire()
    snapshot["authoritySnapshot"]["snapshotFingerprint"] = "sha256:" + "f" * 64
    snapshot["authoritySnapshotFingerprint"] = snapshot["authoritySnapshot"][
        "snapshotFingerprint"
    ]
    snapshot["executionPlan"]["authoritySnapshotFingerprint"] = snapshot[
        "authoritySnapshotFingerprint"
    ]
    _command_digest(snapshot)
    with pytest.raises(ControlledCoordinationError) as changed_snapshot:
        acquire_lane_lease(
            acquisition_factory.repository_root,
            acquisition_factory.source_root,
            snapshot,
        )
    assert changed_snapshot.value.code == "ADMISSION_AUTHORITY_BINDING_MISMATCH"


def test_source_head_drift_rejects_acquisition(acquisition_factory):
    command = acquisition_factory.acquire()
    (acquisition_factory.source_root / "head-drift.txt").write_text(
        "changed\n", encoding="utf-8"
    )
    _git(acquisition_factory.source_root, "add", "head-drift.txt")
    _git(acquisition_factory.source_root, "commit", "-qm", "head drift")

    with pytest.raises(ControlledCoordinationError) as caught:
        acquire_lane_lease(
            acquisition_factory.repository_root,
            acquisition_factory.source_root,
            command,
        )

    assert caught.value.code == "SOURCE_HEAD_CHANGED"


@pytest.mark.parametrize("mutation", ["changed", "missing", "symlink"])
def test_live_authority_file_drift_fails_closed(acquisition_factory, mutation):
    command = acquisition_factory.acquire()
    authority = acquisition_factory.source_root / "status.md"
    if mutation == "changed":
        authority.write_text("changed\n", encoding="utf-8")
        expected = "LIVE_AUTHORITY_SNAPSHOT_MISMATCH"
    elif mutation == "missing":
        authority.unlink()
        expected = "LIVE_AUTHORITY_SNAPSHOT_MISMATCH"
    else:
        replacement = acquisition_factory.source_root / "status-replacement.md"
        replacement.write_bytes(authority.read_bytes())
        authority.unlink()
        authority.symlink_to(replacement.name)
        expected = "LIVE_AUTHORITY_SNAPSHOT_INVALID"

    with pytest.raises(ControlledCoordinationError) as caught:
        acquire_lane_lease(
            acquisition_factory.repository_root,
            acquisition_factory.source_root,
            command,
        )

    assert caught.value.code == expected


def test_acquire_rejects_caller_forged_authority_facts(acquisition_factory):
    command = acquisition_factory.acquire()
    snapshot = command["authoritySnapshot"]
    snapshot["facts"]["project.stage"]["rawValue"] = "FORGED"
    snapshot["facts"]["project.stage"]["normalizedValue"] = "FORGED"
    snapshot["snapshotFingerprint"] = _sha256(
        {key: value for key, value in snapshot.items() if key != "snapshotFingerprint"}
    )
    command["planningRequest"]["authoritySnapshot"] = copy.deepcopy(snapshot)
    bundle = build_provisional_execution_plan(
        acquisition_factory.repository_root, command["planningRequest"]
    )
    command["executionPlan"] = bundle["executionPlan"]
    command["batchPlanId"] = bundle["executionPlan"]["batchPlanId"]
    command["authoritySnapshotFingerprint"] = snapshot["snapshotFingerprint"]
    _command_digest(command)

    with pytest.raises(ControlledCoordinationError) as caught:
        acquire_lane_lease(
            acquisition_factory.repository_root,
            acquisition_factory.source_root,
            command,
        )

    assert caught.value.code == "LIVE_AUTHORITY_SNAPSHOT_MISMATCH"


def test_acquire_rejects_real_development_authority_deny(
    tmp_path, monkeypatch, repository_root, controlled_factory
):
    monkeypatch.setenv(
        "AGENT_EVOLUTION_COORDINATOR_ROOT", str(tmp_path / "coordinator-state")
    )
    source = _committed_source(
        repository_root,
        tmp_path / "denied-project",
        controlled_factory,
        development_authorized=False,
    )
    factory = AcquisitionFactory(repository_root, source, controlled_factory)
    command = factory.acquire()

    with pytest.raises(ControlledCoordinationError) as caught:
        acquire_lane_lease(repository_root, source, command)

    assert command["authoritySnapshot"]["facts"]["permission.development"][
        "normalizedValue"
    ] == "DENY"
    assert caught.value.code == "DEVELOPMENT_AUTHORITY_DENIED"


def test_same_key_changed_payload_and_terminal_replay_fail_closed(
    acquisition_factory
):
    command = acquisition_factory.acquire()
    acquire_lane_lease(
        acquisition_factory.repository_root,
        acquisition_factory.source_root,
        command,
    )
    changed = copy.deepcopy(command)
    changed["asOf"] = "2026-08-13T12:00:01Z"
    _command_digest(changed)
    with pytest.raises(ControlledCoordinationError) as conflict:
        acquire_lane_lease(
            acquisition_factory.repository_root,
            acquisition_factory.source_root,
            changed,
        )
    assert conflict.value.code == "ACQUISITION_IDEMPOTENCY_CONFLICT"

    state_root = Path(os.environ["AGENT_EVOLUTION_COORDINATOR_ROOT"])
    journal_path = next(state_root.glob("*.journal.json"))
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["leases"][0]["state"] = "CLOSED"
    journal["leases"][0]["released"] = True
    journal["receipts"][-1]["journalDigest"] = "sha256:" + "0" * 64
    journal["receipts"][-1]["journalDigest"] = _sha256(journal)
    journal_path.write_bytes(canonical_json_bytes(journal) + b"\n")
    with pytest.raises(ControlledCoordinationError) as terminal:
        acquire_lane_lease(
            acquisition_factory.repository_root,
            acquisition_factory.source_root,
            command,
        )
    assert terminal.value.code == "TERMINAL_ACQUISITION_REPLAY"


def test_planner_snapshot_accounts_for_active_conflicts_and_capacity_without_mutation(
    acquisition_factory, controlled_factory
):
    active_command = acquisition_factory.acquire(max_parallel_lanes=1)
    acquire_lane_lease(
        acquisition_factory.repository_root,
        acquisition_factory.source_root,
        active_command,
    )
    conflicting = acquisition_factory.acquire(max_parallel_lanes=1)
    snapshot = _coordinator_snapshot(acquisition_factory, conflicting)
    original_snapshot = copy.deepcopy(snapshot)
    request = conflicting["planningRequest"]

    without_snapshot = build_provisional_execution_plan(
        acquisition_factory.repository_root, request
    )
    explicit_none = build_provisional_execution_plan(
        acquisition_factory.repository_root, request, coordinator_snapshot=None
    )
    projected = build_provisional_execution_plan(
        acquisition_factory.repository_root,
        request,
        coordinator_snapshot=snapshot,
    )

    assert canonical_json_bytes(without_snapshot) == canonical_json_bytes(explicit_none)
    assert canonical_json_bytes(projected["executionPlan"]) == canonical_json_bytes(
        without_snapshot["executionPlan"]
    )
    assert projected["coordinatorProjection"]["proposedAdmissions"] == []
    assert projected["coordinatorProjection"]["queued"] == [
        {"sliceId": conflicting["sliceId"], "reasons": ["ACTIVE_LEASE_CONFLICT"]}
    ]
    assert projected["executionPlan"]["requiresCoordinatorRecheck"] is True

    disjoint = acquisition_factory.acquire(
        slice_id="slice:neutral-b",
        attempt_id="attempt:neutral-b",
        owner="owner:neutral-b",
        exact_write_set="services/neutral-b",
        lane_name="slice-neutral-b",
        max_parallel_lanes=1,
    )
    capacity_snapshot = _coordinator_snapshot(acquisition_factory, disjoint)
    capacity = build_provisional_execution_plan(
        acquisition_factory.repository_root,
        disjoint["planningRequest"],
        coordinator_snapshot=capacity_snapshot,
    )
    assert capacity["coordinatorProjection"]["queued"] == [
        {
            "sliceId": disjoint["sliceId"],
            "reasons": ["PROJECT_CAPACITY_LIMIT"],
        }
    ]
    assert snapshot == original_snapshot


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("projectId", "other-project"),
        ("baseBatchPlanId", "batch-plan:" + "f" * 24),
        ("journalVersion", 9),
        ("journalDigest", "sha256:" + "f" * 64),
        ("authorizationEnvelopeDigest", "sha256:" + "e" * 64),
        ("conflictPolicyVersion", "controlled-conflict-policy/v2"),
        ("expectedLaneBase", "b" * 40),
        ("recoveryState", "STATE_RECOVERY_REQUIRED"),
    ],
)
def test_planner_rejects_unbound_or_recovering_coordinator_snapshot(
    acquisition_factory, field, value
):
    command = acquisition_factory.acquire()
    acquire_lane_lease(
        acquisition_factory.repository_root,
        acquisition_factory.source_root,
        command,
    )
    snapshot = _coordinator_snapshot(acquisition_factory, command)
    snapshot[field] = value

    with pytest.raises((ControlledPlanningError, SchemaValidationError)):
        build_provisional_execution_plan(
            acquisition_factory.repository_root,
            command["planningRequest"],
            coordinator_snapshot=snapshot,
        )


def test_two_process_simultaneous_acquire_has_exactly_one_success(
    acquisition_factory, tmp_path
):
    first = acquisition_factory.acquire()
    second = acquisition_factory.acquire(
        attempt_id="attempt:neutral-b", lane_name="slice-neutral-b"
    )
    command_paths = []
    for index, command in enumerate((first, second)):
        path = tmp_path / f"command-{index}.json"
        path.write_bytes(canonical_json_bytes(command) + b"\n")
        command_paths.append(path)
    barrier = tmp_path / "start"
    script = """
import json
import sys
import time
from pathlib import Path
from evolution_harness.controlled_coordinator import acquire_lane_lease
from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError
repository, source, command_path, barrier = map(Path, sys.argv[1:])
while not barrier.exists():
    time.sleep(0.001)
command = json.loads(command_path.read_text(encoding='utf-8'))
try:
    lease = acquire_lane_lease(repository, source, command)
    print(json.dumps({'ok': True, 'token': lease['fencingToken']}))
except ControlledCoordinationError as exc:
    print(json.dumps({'ok': False, 'code': exc.code}))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(acquisition_factory.repository_root / "src")
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(acquisition_factory.repository_root),
                str(acquisition_factory.source_root),
                str(command_path),
                str(barrier),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        for command_path in command_paths
    ]
    barrier.touch()
    outputs = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, stderr
        outputs.append(json.loads(stdout))

    assert sum(item["ok"] for item in outputs) == 1
    assert {item.get("token") for item in outputs if item["ok"]} == {1}
