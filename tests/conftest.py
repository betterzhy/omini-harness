from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import pytest

from evolution_harness.controlled_inputs import (
    dependency_graph_digest,
    descriptor_digest,
    envelope_digest,
)
from evolution_harness.controlled_planner import build_provisional_execution_plan
from evolution_harness.hashing import canonical_json_bytes, sha256_bytes


BASE_DESCRIPTOR = {
    "schemaVersion": "controlled-slice-descriptor/v1",
    "sliceId": "slice:neutral-a",
    "state": "READY",
    "portfolioId": "portfolio:neutral",
    "deliveryTrackId": "track:core",
    "sliceClass": "class:ordinary",
    "priority": 0,
    "ownerSet": ["owner:neutral-a"],
    "factFamilySet": ["fact:neutral-a"],
    "publicContractSet": [],
    "producerConsumerSet": [],
    "bindingSet": [],
    "exactWriteSet": ["services/neutral-a"],
    "ephemeralWriteSet": ["build/neutral-a"],
    "sharedArtifactSet": [],
    "dependencySet": [],
    "migrationResourceSet": [],
    "requiredGates": ["unit", "integration"],
    "reviewPolicy": {"reviewerRole": "deep-reviewer", "minimumVerdict": "GO_ZERO_FINDINGS"},
    "authorizationClass": "action:ordinary-development",
    "authorityReferences": ["authority/slice-neutral-a.yaml"],
}

BASE_ENVELOPE = {
    "schemaVersion": "controlled-authorization-envelope/v1",
    "envelopeId": "envelope:neutral",
    "issuerId": "authority-neutral",
    "issuerAuthorityReference": "authority/portfolio.yaml",
    "issuerAuthorityDigest": "sha256:" + "1" * 64,
    "projectId": "neutral-project",
    "portfolioId": "portfolio:neutral",
    "permittedDeliveryTracks": ["track:core"],
    "permittedSliceClasses": ["class:ordinary"],
    "permittedPathPrefixes": ["services", "build"],
    "permittedActionClasses": ["action:ordinary-development"],
    "maxParallelLanes": 3,
    "requiredTests": ["pytest"],
    "requiredGates": ["unit", "integration"],
    "requiredReviewers": ["deep-reviewer"],
    "minimumReviewVerdict": "GO_ZERO_FINDINGS",
    "refreshPolicy": "REVALIDATE_NO_SCOPE_WIDENING",
    "issuedAt": "2026-08-13T00:00:00Z",
    "expiresAt": "2026-08-14T00:00:00Z",
    "deniedActions": ["action:database-write", "action:push", "action:deploy"],
    "stopConditions": ["authority-drift", "gate-failure", "writeset-breach"],
}


class ControlledPlanningFactory:
    def descriptor(self, **changes):
        value = copy.deepcopy(BASE_DESCRIPTOR)
        value.update(changes)
        value["descriptorDigest"] = descriptor_digest(value)
        return value

    def envelope(self, **changes):
        value = copy.deepcopy(BASE_ENVELOPE)
        value.update(changes)
        value["envelopeDigest"] = envelope_digest(value)
        return value

    def authority_snapshot(
        self, *, descriptors, envelope, contract_registry_digest, dependency_graph_digest_value
    ):
        authority_records = [
            {
                "id": "authority-neutral", "path": "authority/portfolio.yaml",
                "role": "CANONICAL", "sha256": "1" * 64,
            },
            {
                "id": "authority-planning", "path": "authority/controlled-planning.yaml",
                "role": "CANONICAL", "sha256": "6" * 64,
            },
        ]
        descriptor_paths = sorted({
            path for descriptor in descriptors for path in descriptor["authorityReferences"]
            if path != "authority/portfolio.yaml"
        })
        authority_records.extend(
            {"id": f"authority-slice-{index:02d}", "path": path, "role": "CANONICAL", "sha256": "5" * 64}
            for index, path in enumerate(descriptor_paths)
        )
        authority_records.sort(key=lambda item: item["id"])
        descriptor_digests = canonical_json_bytes(
            sorted(item["descriptorDigest"] for item in descriptors)
        ).decode("utf-8")
        normalized_facts = {
            "controlled_planning.mode": "CONTROLLED_PARALLEL",
            "controlled_planning.contract_registry_digest": contract_registry_digest,
            "controlled_planning.dependency_graph_digest": dependency_graph_digest_value,
            "controlled_planning.authorization_envelope_digest": envelope["envelopeDigest"],
            "controlled_planning.slice_descriptor_digests": descriptor_digests,
            "controlled_planning.conflict_policy_version": "controlled-conflict-policy/v1",
        }
        value = {
            "schemaVersion": "authority-snapshot/v1", "integrationId": "neutral-shadow",
            "projectId": "neutral-project",
            "sourceRevision": {
                "kind": "GIT", "head": "a" * 40, "tree": "b" * 40,
                "authoritySetStatus": "CLEAN_FOR_AUTHORITY_SET",
                "authoritySetDigest": "sha256:" + sha256_bytes(canonical_json_bytes(authority_records)),
            },
            "authorities": authority_records,
            "facts": {
                fact_id: {"owner": "authority-planning", "sourcePath": "authority/controlled-planning.yaml", "rawValue": normalized_value, "normalizedValue": normalized_value}
                for fact_id, normalized_value in sorted(normalized_facts.items())
            },
            "conflicts": [], "missingFacts": [], "excludedPaths": [], "gate": "PASS",
        }
        value["snapshotFingerprint"] = "sha256:" + sha256_bytes(canonical_json_bytes(value))
        return value

    def request(self, *descriptors, envelope=None, **changes):
        selected_descriptors = list(descriptors)
        selected_envelope = envelope or self.envelope()
        contract_registry_digest = "sha256:" + "2" * 64
        graph_digest = dependency_graph_digest(selected_descriptors)
        value = {
            "schemaVersion": "controlled-planning-request/v1", "planningMode": "CONTROLLED_PARALLEL",
            "projectId": "neutral-project", "batchBaseCommit": "a" * 40,
            "authoritySnapshot": self.authority_snapshot(
                descriptors=selected_descriptors, envelope=selected_envelope,
                contract_registry_digest=contract_registry_digest, dependency_graph_digest_value=graph_digest,
            ),
            "contractRegistryDigest": contract_registry_digest, "dependencyGraphDigest": graph_digest,
            "conflictPolicyVersion": "controlled-conflict-policy/v1",
            "harnessVersion": "agent-evolution-harness/0.1.0", "asOf": "2026-08-13T12:00:00Z",
            "authorizationEnvelope": selected_envelope, "slices": selected_descriptors,
        }
        value.update(changes)
        return value


@dataclass(frozen=True)
class CoordinatorStateFactory:
    repository_root: Path
    controlled_factory: object
    project_execution_key: str = "project-execution:" + "1" * 64

    def acquire_command(
        self, token: int, *, project_execution_key: str | None = None
    ):
        del project_execution_key
        suffix = f"neutral-{token}"
        descriptor = self.controlled_factory.descriptor(
            sliceId=f"slice:{suffix}",
            ownerSet=[f"owner:{suffix}"],
            factFamilySet=[f"fact:{suffix}"],
            exactWriteSet=[f"services/{suffix}"],
            ephemeralWriteSet=[f"build/{suffix}"],
        )
        request = self.controlled_factory.request(descriptor)
        bundle = build_provisional_execution_plan(self.repository_root, request)
        plan = bundle["executionPlan"]
        footprint = bundle["conflictReport"]["footprints"][0]
        admission_binding = {
            "projectId": plan["projectId"],
            "sliceId": descriptor["sliceId"],
            "attemptId": f"attempt:{suffix}",
            "originalSourceRoot": "/projects/neutral",
            "laneRoot": f"/projects/neutral-lanes/{suffix}",
        }
        proof = {
            "factId": "controlled_coordination.admission.bindings",
            "manifestAuthorityId": "authority-planning",
            "manifestAuthorityReference": "authority/controlled-planning.yaml",
            "manifestAuthorityDigest": "sha256:" + "6" * 64,
            "binding": admission_binding,
        }
        proof["proofDigest"] = "sha256:" + sha256_bytes(canonical_json_bytes(proof))
        command = {
            "schemaVersion": "controlled-coordinator-acquire-command/v1",
            "projectId": plan["projectId"],
            "batchPlanId": plan["batchPlanId"],
            "sliceId": descriptor["sliceId"],
            "attemptId": admission_binding["attemptId"],
            "authoritySnapshotFingerprint": plan["authoritySnapshotFingerprint"],
            "authorizationEnvelopeDigest": plan["authorizationEnvelopeDigest"],
            "conflictPolicyVersion": plan["conflictPolicyVersion"],
            "asOf": plan["asOf"],
            "planningRequest": request,
            "executionPlan": plan,
            "sliceDescriptor": descriptor,
            "authorizationEnvelope": request["authorizationEnvelope"],
            "authoritySnapshot": request["authoritySnapshot"],
            "admissionAuthorityProof": proof,
            "fullFootprint": footprint,
            "originalSourceRoot": admission_binding["originalSourceRoot"],
            "laneRoot": admission_binding["laneRoot"],
            "expectedLaneBase": plan["batchBaseCommit"],
        }
        command["commandDigest"] = "sha256:" + sha256_bytes(
            canonical_json_bytes(command)
        )
        return command

    def receipt(self, version: int, *, project_execution_key: str | None = None):
        key = project_execution_key or self.project_execution_key
        command = self.acquire_command(version, project_execution_key=key)
        return {
            "schemaVersion": "controlled-coordinator-receipt/v1",
            "receiptId": "coordinator-receipt:" + f"{version:024x}",
            "receiptType": "ACQUIRE",
            "projectExecutionKey": key,
            "previousJournalVersion": version - 1,
            "nextJournalVersion": version,
            "commandDigest": command["commandDigest"],
            "fencingToken": version,
            "previousState": None,
            "nextState": "ADMITTED",
            "authoritySnapshotFingerprint": command[
                "authoritySnapshotFingerprint"
            ],
            "journalDigest": "sha256:" + "d" * 64,
            "recordedAt": command["asOf"],
            "evidence": {"command": command},
        }

    def lease(self, token: int, *, project_execution_key: str | None = None):
        key = project_execution_key or self.project_execution_key
        command = self.acquire_command(token, project_execution_key=key)
        return {
            "schemaVersion": "controlled-execution-lease/v1",
            "projectExecutionKey": key,
            "leaseId": "lease:" + f"{token:024x}",
            "batchPlanId": command["batchPlanId"],
            "sliceId": command["sliceId"],
            "attemptId": command["attemptId"],
            "authoritySnapshotFingerprint": command[
                "authoritySnapshotFingerprint"
            ],
            "authorizationEnvelopeDigest": command[
                "authorizationEnvelopeDigest"
            ],
            "conflictPolicyVersion": command["conflictPolicyVersion"],
            "descriptorDigest": command["sliceDescriptor"]["descriptorDigest"],
            "fullFootprint": copy.deepcopy(command["fullFootprint"]),
            "planningFootprints": [copy.deepcopy(command["fullFootprint"])],
            "originalSourceRoot": command["originalSourceRoot"],
            "laneRoot": command["laneRoot"],
            "lanePhysicalIdentity": {
                "device": 1, "inode": token, "type": "DIRECTORY"
            },
            "expectedLaneBase": command["expectedLaneBase"],
            "fencingToken": token,
            "state": "ADMITTED",
            "candidateIdentity": None,
            "acquiredAt": command["asOf"],
            "lastTransitionAt": command["asOf"],
            "released": False,
            "recoveryStatus": "CLEAR",
        }

    def journal(self, version: int, *, project_execution_key: str | None = None):
        key = project_execution_key or self.project_execution_key
        receipt = self.receipt(version, project_execution_key=key)
        journal = {
            "schemaVersion": "controlled-coordinator-journal/v1",
            "projectExecutionKey": key,
            "journalVersion": version,
            "nextFencingToken": version + 1,
            "recoveryState": "CLEAR",
            "recoveryEvidence": None,
            "leases": [
                self.lease(item, project_execution_key=key)
                for item in range(1, version + 1)
            ],
            "receipts": [
                self.receipt(item, project_execution_key=key)
                for item in range(1, version + 1)
            ],
            "integrationTransactions": [],
        }
        for index in range(len(journal["receipts"])):
            prefix = copy.deepcopy(journal)
            prefix["journalVersion"] = index + 1
            prefix["nextFencingToken"] = index + 2
            prefix["leases"] = prefix["leases"][: index + 1]
            prefix["receipts"] = prefix["receipts"][: index + 1]
            prefix["receipts"][-1]["journalDigest"] = "sha256:" + "0" * 64
            journal["receipts"][index]["journalDigest"] = (
                "sha256:" + sha256_bytes(canonical_json_bytes(prefix))
            )
        return journal, copy.deepcopy(journal["receipts"][-1])


@pytest.fixture
def repository_root():
    return Path(__file__).parents[1]


@pytest.fixture
def controlled_factory():
    return ControlledPlanningFactory()


@pytest.fixture
def coordinator_state_factory(repository_root, controlled_factory):
    return CoordinatorStateFactory(repository_root, controlled_factory)
