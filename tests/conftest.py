from __future__ import annotations

import copy
from pathlib import Path

import pytest

from evolution_harness.controlled_inputs import (
    dependency_graph_digest,
    descriptor_digest,
    envelope_digest,
)
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
        authority_records = [{
            "id": "authority-neutral", "path": "authority/portfolio.yaml",
            "role": "CANONICAL", "sha256": "1" * 64,
        }]
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
            "controlled_planning.batch_base_commit": "a" * 40,
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
                fact_id: {"owner": "authority-neutral", "sourcePath": "authority/portfolio.yaml", "rawValue": normalized_value, "normalizedValue": normalized_value}
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


@pytest.fixture
def repository_root():
    return Path(__file__).parents[1]


@pytest.fixture
def controlled_factory():
    return ControlledPlanningFactory()
