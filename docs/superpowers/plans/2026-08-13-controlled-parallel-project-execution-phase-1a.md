# Controlled Parallel Project Execution Phase 1A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a project-neutral, deterministic, read-only Phase 1A planner that validates controlled Slice and authorization inputs, explains conflicts, and emits a provisional execution plan without admitting or executing work.

**Architecture:** Add strict Draft 2020-12 input/output schemas, then implement three pure layers: input normalization and digest verification, conflict-graph construction, and authorization/scheduling. Expose only `harness planning plan --request <yaml>`; it reads one already-authoritative snapshot request and writes results to stdout. Project-scoped leases, CAS, worktree creation, process sandboxing, integration transactions, and Pay-Nexus adoption remain outside Phase 1A.

**Tech Stack:** Python 3.12+, standard library, PyYAML, jsonschema Draft 2020-12, pytest, existing `SchemaStore`, `canonical_json_bytes`, `sha256_bytes`, and `safe_relative_path`.

## Global Constraints

- Work only in the isolated Harness branch/worktree; never modify Pay-Nexus.
- Phase 1A is read-only: no project writes, generated planner artifacts, worktree creation, lease/CAS state, Git mutation, task launch, or lifecycle mutation.
- The planner is deterministic and LLM-free. Time enters only through the required `asOf` request field.
- `planningMode: CONTROLLED_PARALLEL` is explicit adoption. If the model is absent, existing project flows remain unchanged and serial; a partially declared model is invalid and is never treated as legacy input.
- Every schema uses Draft 2020-12 and `additionalProperties: false`; unknown or omitted conflict facts fail closed.
- Set-valued fields sort lexicographically for digests and outputs. `requiredGates` retains declared order.
- Repository-relative paths pass `safe_relative_path`; physical no-follow write enforcement belongs to Phase 1B.
- An execution plan is always `provisional: true` and `requiresCoordinatorRecheck: true`; it never grants admission.
- Policy version 1 proposes at most `min(envelope.maxParallelLanes, 3)` Slices and at most one Slice per conflict cluster.
- Public cross-owner contracts, migrations, and `global:*` shared artifacts are project-wide serial barriers.
- Full Harness regression gates and fixed-candidate review remain mandatory before Phase 1B may consume Phase 1A interfaces.

## Locked Data Contracts

### Controlled Slice descriptor

`controlled-slice-descriptor/v1` requires exactly:

```text
schemaVersion, sliceId, state, portfolioId, deliveryTrackId, sliceClass,
priority, ownerSet, factFamilySet, publicContractSet, producerConsumerSet,
bindingSet, exactWriteSet, ephemeralWriteSet, sharedArtifactSet,
dependencySet, migrationResourceSet, requiredGates, reviewPolicy,
authorizationClass, authorityReferences, descriptorDigest
```

- `state`: `PROPOSED | READY | ADMITTED | ACTIVE | FIXED_CANDIDATE | REVIEW_GO | QUEUED_FOR_INTEGRATION | INTEGRATING | CLOSED | BLOCKED | NO_GO | STALE | CANCELLED`.
- IDs use `^[a-z0-9][a-z0-9._:-]*$`; `priority` is an integer `>= 0`, where a smaller number is higher priority.
- All `*Set`, `dependencySet`, and `authorityReferences` arrays use `uniqueItems: true`.
- `producerConsumerSet` items are `{producer, consumer}` with no extra fields.
- `exactWriteSet`, `ephemeralWriteSet`, and `authorityReferences` are repository-relative paths.
- `reviewPolicy` is `{reviewerRole, minimumVerdict}` and Phase 1A accepts only `minimumVerdict: GO_ZERO_FINDINGS`.
- `descriptorDigest` is `sha256:` plus SHA-256 of canonical normalized JSON excluding `descriptorDigest`.

### Authorization envelope

`controlled-authorization-envelope/v1` requires exactly:

```text
schemaVersion, envelopeId, issuerId, issuerAuthorityReference,
issuerAuthorityDigest, projectId, portfolioId, permittedDeliveryTracks,
permittedSliceClasses, permittedPathPrefixes, permittedActionClasses,
maxParallelLanes, requiredTests, requiredGates, requiredReviewers,
minimumReviewVerdict, refreshPolicy, issuedAt, expiresAt, deniedActions,
stopConditions, envelopeDigest
```

- `maxParallelLanes` is `1..3`.
- `minimumReviewVerdict` is `GO_ZERO_FINDINGS`.
- `refreshPolicy` is `REVALIDATE_NO_SCOPE_WIDENING`.
- `issuerAuthorityDigest` and `envelopeDigest` match `^sha256:[0-9a-f]{64}$`.
- `permittedPathPrefixes` are repository-relative path prefixes.
- Every array except `requiredGates` is normalized as a set. `requiredGates` is an ordered, duplicate-free sequence.
- `envelopeDigest` covers every field above except itself.

### Planning request

`controlled-planning-request/v1` requires exactly:

```text
schemaVersion, planningMode, projectId, batchBaseCommit, authoritySnapshot,
contractRegistryDigest, dependencyGraphDigest, conflictPolicyVersion,
harnessVersion, asOf, authorizationEnvelope, slices
```

- `planningMode` is `CONTROLLED_PARALLEL`.
- `authoritySnapshot` references `authority-snapshot/v1`, must have `gate: PASS`, and its fingerprint must recompute exactly. Phase 1A accepts only `sourceRevision.kind: GIT`, `authoritySetStatus: CLEAN_FOR_AUTHORITY_SET`, and `sourceRevision.head == batchBaseCommit`; content-only or dirty snapshots cannot authorize concurrent development.
- `conflictPolicyVersion` is `controlled-conflict-policy/v1`.
- `harnessVersion` is `agent-evolution-harness/0.1.0`.
- `projectId` must match the authority snapshot and envelope.
- `batchBaseCommit` is 40 or 64 lowercase hex characters.
- `contractRegistryDigest` and `dependencyGraphDigest` are `sha256:` digests.
- `asOf`, `issuedAt`, and `expiresAt` are explicit RFC 3339 timestamps; no call reads the system clock.
- The snapshot must own these exact facts, each with a string `normalizedValue`: `controlled_planning.mode`, `controlled_planning.batch_base_commit`, `controlled_planning.contract_registry_digest`, `controlled_planning.dependency_graph_digest`, `controlled_planning.authorization_envelope_digest`, `controlled_planning.slice_descriptor_digests`, and `controlled_planning.conflict_policy_version`. `slice_descriptor_digests` is the UTF-8 canonical JSON text of the sorted digest array.
- Request values must equal those owned facts. `dependencyGraphDigest` must also recompute from canonical JSON of sorted `{sliceId, dependsOn}` records, `sliceDescriptorDigests` must equal every normalized descriptor digest exactly, every descriptor authority reference must name a snapshot authority path, and the envelope issuer reference/digest must match one snapshot authority record.

### Output contracts

- `controlled-conflict-report/v1` requires exactly `schemaVersion`, `projectId`, `authoritySnapshotFingerprint`, `conflictPolicyVersion`, `footprints`, `edges`, `clusters`, and `conflictReportId`. Each footprint contains `sliceId`, every normalized conflict-resource field from its descriptor, and `conflictFootprintId`; each edge is `{leftSliceId, rightSliceId, reasons}`; each cluster is `{clusterId, sliceIds}`.
- `controlled-authorization-decision/v1` requires exactly `schemaVersion`, `projectId`, `authoritySnapshotFingerprint`, `envelopeId`, `envelopeDigest`, `asOf`, `decisions`, `gate`, and `authorizationDecisionId`. Every Slice appears once as `{sliceId, result, reasons}`, where `result` is `ALLOW|REJECT`.
- `controlled-execution-plan/v1` requires exactly `schemaVersion`, `projectId`, `batchBaseCommit`, `authoritySnapshotFingerprint`, `contractRegistryDigest`, `dependencyGraphDigest`, `authorizationEnvelopeDigest`, `conflictPolicyVersion`, `harnessVersion`, `asOf`, `conflictReportId`, `authorizationDecisionId`, `provisional`, `requiresCoordinatorRecheck`, `projectLaneCap`, `proposedAdmissions`, `queued`, `blocked`, `rejected`, `executionRequirements`, `mandatoryStopConditions`, and `batchPlanId`.
- A proposed entry is `{sliceId, conflictClusterId, descriptorDigest, exactWriteSetDigest}`. Queued, blocked, and rejected entries are `{sliceId, reasons}`. `executionRequirements` is exactly `{requiredTests, requiredGates, requiredReviewers, minimumReviewVerdict, sliceRequirements}`; every `sliceRequirements` item is `{sliceId, requiredGates, reviewPolicy}` for one proposed Slice.
- Output arrays and reason codes are canonical and unique; `requiredGates` alone preserves declared order. All three IDs hash their complete normalized output object excluding only the object's own ID field, so `asOf`, envelope digest, source digests, decisions, and selection results are identity-bound.
- IDs are `conflict-report:<24 hex>`, `authorization-decision:<24 hex>`, `conflict-cluster:<24 hex>`, `footprint:<24 hex>`, and `batch-plan:<24 hex>`.

---

### Task 1: Strict schemas, canonical normalization, and digest verification

**Files:**

- Create: `core/schemas/controlled-slice-descriptor.schema.json`
- Create: `core/schemas/controlled-authorization-envelope.schema.json`
- Create: `core/schemas/controlled-planning-request.schema.json`
- Create: `core/schemas/controlled-conflict-report.schema.json`
- Create: `core/schemas/controlled-authorization-decision.schema.json`
- Create: `core/schemas/controlled-execution-plan.schema.json`
- Create: `src/evolution_harness/controlled_inputs.py`
- Create: `tests/conftest.py`
- Create: `tests/test_controlled_inputs.py`

**Interfaces:**

- Consumes: `SchemaStore.validate(schema_path, instance)`, `canonical_json_bytes(value)`, `sha256_bytes(data)`, and `safe_relative_path(value, label=field_name)`.
- Produces:

```text
ControlledPlanningError(ValueError), with public attribute code: str
descriptor_digest(descriptor: dict[str, Any]) -> str
exact_writeset_digest(descriptor: dict[str, Any]) -> str
envelope_digest(envelope: dict[str, Any]) -> str
dependency_graph_digest(descriptors: list[dict[str, Any]]) -> str
parse_rfc3339(value: str) -> datetime
normalize_slice_descriptor(repository_root: Path, value: dict[str, Any]) -> dict[str, Any]
normalize_authorization_envelope(repository_root: Path, value: dict[str, Any]) -> dict[str, Any]
normalize_planning_request(repository_root: Path, value: dict[str, Any]) -> dict[str, Any]
load_planning_request(repository_root: Path, path: Path) -> dict[str, Any]
```

- `ControlledPlanningError.code` values introduced here: `DIGEST_MISMATCH`, `AUTHORITY_SNAPSHOT_NO_GO`, `AUTHORITY_SNAPSHOT_FINGERPRINT_MISMATCH`, `AUTHORITY_SET_DIGEST_MISMATCH`, `AUTHORITY_RECORD_DUPLICATE`, `AUTHORITY_SOURCE_NOT_CLEAN_GIT`, `AUTHORITY_FACT_MISSING`, `AUTHORITY_FACT_MISMATCH`, `AUTHORITY_REFERENCE_UNBOUND`, `BATCH_BASE_MISMATCH`, `DEPENDENCY_GRAPH_DIGEST_MISMATCH`, `DUPLICATE_SLICE_ID`, `PROJECT_ID_MISMATCH`, `UNSAFE_DECLARED_PATH`, `TIMESTAMP_INVALID`, and `AUTHORIZATION_INTERVAL_INVALID`.

- [ ] **Step 1: Add one reusable neutral test factory and write normalization failure tests**

Create a `ControlledPlanningFactory` plus `repository_root` and `controlled_factory` fixtures in `tests/conftest.py`. The factory uses neutral identifiers only and exposes `descriptor(**changes)`, `envelope(**changes)`, `authority_snapshot(*, descriptors, envelope, contract_registry_digest, dependency_graph_digest_value)`, and `request(*descriptors, envelope=None, **changes)`. Each method applies changes, normalizes set ordering for digest calculation, fills the correct digest, and binds the request values into the authority snapshot. Use this exact base data:

```python
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
```

Build the reusable factory and fixtures as follows:

```python
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
        self,
        *,
        descriptors,
        envelope,
        contract_registry_digest,
        dependency_graph_digest_value,
    ):
        authority_records = [{
            "id": "authority-neutral",
            "path": "authority/portfolio.yaml",
            "role": "CANONICAL",
            "sha256": "1" * 64,
        }]
        descriptor_paths = sorted({
            path
            for descriptor in descriptors
            for path in descriptor["authorityReferences"]
            if path != "authority/portfolio.yaml"
        })
        authority_records.extend(
            {
                "id": f"authority-slice-{index:02d}",
                "path": path,
                "role": "CANONICAL",
                "sha256": "5" * 64,
            }
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
            "schemaVersion": "authority-snapshot/v1",
            "integrationId": "neutral-shadow",
            "projectId": "neutral-project",
            "sourceRevision": {
                "kind": "GIT",
                "head": "a" * 40,
                "tree": "b" * 40,
                "authoritySetStatus": "CLEAN_FOR_AUTHORITY_SET",
                "authoritySetDigest": "sha256:" + sha256_bytes(
                    canonical_json_bytes(authority_records)
                ),
            },
            "authorities": authority_records,
            "facts": {
                fact_id: {
                    "owner": "authority-neutral",
                    "sourcePath": "authority/portfolio.yaml",
                    "rawValue": normalized_value,
                    "normalizedValue": normalized_value,
                }
                for fact_id, normalized_value in sorted(normalized_facts.items())
            },
            "conflicts": [],
            "missingFacts": [],
            "excludedPaths": [],
            "gate": "PASS",
        }
        value["snapshotFingerprint"] = "sha256:" + sha256_bytes(canonical_json_bytes(value))
        return value

    def request(self, *descriptors, envelope=None, **changes):
        selected_descriptors = list(descriptors)
        selected_envelope = envelope or self.envelope()
        contract_registry_digest = "sha256:" + "2" * 64
        graph_digest = dependency_graph_digest(selected_descriptors)
        value = {
            "schemaVersion": "controlled-planning-request/v1",
            "planningMode": "CONTROLLED_PARALLEL",
            "projectId": "neutral-project",
            "batchBaseCommit": "a" * 40,
            "authoritySnapshot": self.authority_snapshot(
                descriptors=selected_descriptors,
                envelope=selected_envelope,
                contract_registry_digest=contract_registry_digest,
                dependency_graph_digest_value=graph_digest,
            ),
            "contractRegistryDigest": contract_registry_digest,
            "dependencyGraphDigest": graph_digest,
            "conflictPolicyVersion": "controlled-conflict-policy/v1",
            "harnessVersion": "agent-evolution-harness/0.1.0",
            "asOf": "2026-08-13T12:00:00Z",
            "authorizationEnvelope": selected_envelope,
            "slices": selected_descriptors,
        }
        value.update(changes)
        return value


@pytest.fixture
def repository_root():
    return Path(__file__).parents[1]


@pytest.fixture
def controlled_factory():
    return ControlledPlanningFactory()
```

Import `canonical_json_bytes`, `sha256_bytes`, `dependency_graph_digest`, `descriptor_digest`, and `envelope_digest` explicitly. Do not read Pay-Nexus or use its identifiers in these fixtures.

Add these tests:

```python
def test_descriptor_normalizes_sets_but_preserves_gate_order(repository_root, controlled_factory):
    value = controlled_factory.descriptor(ownerSet=["owner:z", "owner:a"])
    normalized = normalize_slice_descriptor(repository_root, value)
    assert normalized["ownerSet"] == ["owner:a", "owner:z"]
    assert normalized["requiredGates"] == ["unit", "integration"]


def test_envelope_digest_covers_every_authoritative_field(repository_root, controlled_factory):
    original = controlled_factory.envelope()
    for field, original_value in original.items():
        if field == "envelopeDigest":
            continue
        invalid = copy.deepcopy(original)
        if isinstance(original_value, list):
            invalid[field] = [*original_value, "mutation:value"]
        elif isinstance(original_value, int):
            invalid[field] = original_value - 1
        else:
            invalid[field] = original_value + "-changed"
        assert envelope_digest(invalid) != original["envelopeDigest"], field


@pytest.mark.parametrize("path", ["", "/absolute", "../escape", "a/../b", "./x"])
def test_declared_paths_reject_unsafe_values(repository_root, controlled_factory, path):
    value = controlled_factory.descriptor()
    value["exactWriteSet"] = [path]
    value["descriptorDigest"] = "sha256:" + "0" * 64
    with pytest.raises((SchemaValidationError, ControlledPlanningError)):
        normalize_slice_descriptor(repository_root, value)


def test_partial_controlled_descriptor_does_not_fall_back_to_serial(repository_root, controlled_factory):
    request = controlled_factory.request(controlled_factory.descriptor())
    del request["slices"][0]["bindingSet"]
    with pytest.raises(SchemaValidationError, match="bindingSet"):
        normalize_planning_request(repository_root, request)


def test_self_consistent_descriptor_cannot_escape_snapshot_binding(repository_root, controlled_factory):
    request = controlled_factory.request(controlled_factory.descriptor())
    request["slices"][0]["ownerSet"] = ["owner:injected"]
    request["slices"][0]["descriptorDigest"] = descriptor_digest(request["slices"][0])
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "AUTHORITY_FACT_MISMATCH"


def test_self_consistent_envelope_cannot_escape_snapshot_binding(repository_root, controlled_factory):
    request = controlled_factory.request(controlled_factory.descriptor())
    request["authorizationEnvelope"]["maxParallelLanes"] = 2
    request["authorizationEnvelope"]["envelopeDigest"] = envelope_digest(
        request["authorizationEnvelope"]
    )
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "AUTHORITY_FACT_MISMATCH"


def test_duplicate_slice_identity_is_rejected(repository_root, controlled_factory):
    descriptor = controlled_factory.descriptor()
    request = controlled_factory.request(descriptor, copy.deepcopy(descriptor))
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "DUPLICATE_SLICE_ID"


def test_unknown_envelope_property_is_rejected(repository_root, controlled_factory):
    envelope = controlled_factory.envelope()
    envelope["undeclaredAuthority"] = True
    request = controlled_factory.request(controlled_factory.descriptor(), envelope=envelope)
    with pytest.raises(SchemaValidationError, match="undeclaredAuthority"):
        normalize_planning_request(repository_root, request)


def test_stale_descriptor_digest_is_rejected(repository_root, controlled_factory):
    request = controlled_factory.request(controlled_factory.descriptor())
    request["slices"][0]["priority"] = 99
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "DIGEST_MISMATCH"


@pytest.mark.parametrize("kind,status", [
    ("CONTENT", "CONTENT_SNAPSHOT"),
    ("GIT", "DIRTY_AUTHORITY_SET"),
])
def test_concurrent_planning_requires_clean_git_authority_snapshot(
    repository_root, controlled_factory, kind, status
):
    request = controlled_factory.request(controlled_factory.descriptor())
    request["authoritySnapshot"]["sourceRevision"].update({
        "kind": kind,
        "authoritySetStatus": status,
    })
    snapshot = request["authoritySnapshot"]
    snapshot["snapshotFingerprint"] = "sha256:" + sha256_bytes(
        canonical_json_bytes({key: value for key, value in snapshot.items() if key != "snapshotFingerprint"})
    )
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "AUTHORITY_SOURCE_NOT_CLEAN_GIT"
```

Also add focused negatives for an authority-set digest mismatch, duplicate authority ID/path, a missing required authority fact, a fact whose `normalizedValue` is not a string, `batchBaseCommit` differing from the clean Git snapshot HEAD, a dependency graph digest that matches the snapshot fact but not the canonical descriptor graph, a descriptor authority reference removed from `authoritySnapshot.authorities`, an envelope issuer digest differing from the matched authority record, and `issuedAt >= expiresAt`. Recompute the snapshot fingerprint in the test after intentional snapshot mutation so each negative reaches the intended semantic check rather than failing earlier.

- [ ] **Step 2: Run the focused tests to verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_controlled_inputs.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: evolution_harness.controlled_inputs`.

- [ ] **Step 3: Add the six strict JSON schemas**

Implement the locked contracts above using the repository's existing pattern:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://agent-evolution.local/core/schemas/controlled-slice-descriptor.schema.json",
  "type": "object",
  "required": ["schemaVersion", "sliceId", "state", "portfolioId", "deliveryTrackId", "sliceClass", "priority", "ownerSet", "factFamilySet", "publicContractSet", "producerConsumerSet", "bindingSet", "exactWriteSet", "ephemeralWriteSet", "sharedArtifactSet", "dependencySet", "migrationResourceSet", "requiredGates", "reviewPolicy", "authorizationClass", "authorityReferences", "descriptorDigest"],
  "properties": {
    "schemaVersion": {"const": "controlled-slice-descriptor/v1"},
    "descriptorDigest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
  },
  "additionalProperties": false
}
```

The fragment shows the identity and strict-object pattern, not an abbreviated deliverable: define a `properties` schema for every required field named in the locked contracts. Use `$defs` for the common ID, digest, path, ordered-gate, string-set, reason-code, review-policy, and output-entry shapes. Use `$ref` from the request schema to the existing authority snapshot plus the new descriptor and envelope `$id` values. Enumerate every state and reason code defined in this plan; use `minLength: 1` for paths before semantic path validation; require `uniqueItems: true` for all set-valued and output arrays. Semantic canonical order is verified by Python tests.

- [ ] **Step 4: Implement normalization and digest verification**

Create `controlled_inputs.py` with no filesystem writes:

```python
from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .hashing import canonical_json_bytes, sha256_bytes
from .paths import PathBoundaryError, safe_relative_path
from .schema import SchemaStore

SET_FIELDS = (
    "ownerSet", "factFamilySet", "publicContractSet", "bindingSet",
    "exactWriteSet", "ephemeralWriteSet", "sharedArtifactSet",
    "dependencySet", "migrationResourceSet", "authorityReferences",
)
ENVELOPE_SET_FIELDS = (
    "permittedDeliveryTracks", "permittedSliceClasses", "permittedPathPrefixes",
    "permittedActionClasses", "requiredTests", "requiredReviewers",
    "deniedActions", "stopConditions",
)
PATH_FIELDS = ("exactWriteSet", "ephemeralWriteSet", "authorityReferences")


class ControlledPlanningError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _sha256(payload: Any) -> str:
    return "sha256:" + sha256_bytes(canonical_json_bytes(payload))


def _normalize_descriptor_fields(descriptor: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(descriptor)
    for field in SET_FIELDS:
        payload[field] = sorted(payload[field])
    payload["producerConsumerSet"] = sorted(
        payload["producerConsumerSet"],
        key=lambda item: (item["producer"], item["consumer"]),
    )
    for field in PATH_FIELDS:
        payload[field] = [
            safe_relative_path(path, label=field).as_posix()
            for path in payload[field]
        ]
    return payload


def _normalize_envelope_fields(envelope: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(envelope)
    for field in ENVELOPE_SET_FIELDS:
        payload[field] = sorted(payload[field])
    payload["permittedPathPrefixes"] = [
        safe_relative_path(path, label="permittedPathPrefixes").as_posix()
        for path in payload["permittedPathPrefixes"]
    ]
    return payload


def descriptor_digest(descriptor: dict[str, Any]) -> str:
    payload = _normalize_descriptor_fields(descriptor)
    return _sha256({key: value for key, value in payload.items() if key != "descriptorDigest"})


def exact_writeset_digest(descriptor: dict[str, Any]) -> str:
    return _sha256(sorted(descriptor["exactWriteSet"]))


def envelope_digest(envelope: dict[str, Any]) -> str:
    payload = _normalize_envelope_fields(envelope)
    return _sha256({key: value for key, value in payload.items() if key != "envelopeDigest"})


def dependency_graph_digest(descriptors: list[dict[str, Any]]) -> str:
    graph = [
        {"sliceId": item["sliceId"], "dependsOn": sorted(item["dependencySet"])}
        for item in sorted(descriptors, key=lambda item: item["sliceId"])
    ]
    return _sha256(graph)


def parse_rfc3339(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ControlledPlanningError("TIMESTAMP_INVALID", f"timestamp must include an offset: {value}")
    return parsed
```

Validate raw input first so duplicate array items cannot disappear during normalization. Normalize `producerConsumerSet` by `(producer, consumer)`, set fields lexicographically, and each path with `safe_relative_path(value, label=field_name).as_posix()`. Catch `PathBoundaryError` and raise `ControlledPlanningError("UNSAFE_DECLARED_PATH", str(exc)) from exc`. Validate normalized output again, then compare its digest.

Perform request-level checks in this stable order:

1. Reject duplicate `sliceId` values before building an index.
2. Recompute `authoritySnapshot.snapshotFingerprint` from the snapshot excluding that field and `sourceRevision.authoritySetDigest` from the canonical `authorities` array. Reject duplicate authority IDs or paths. Require `gate == "PASS"` with empty `conflicts` and `missingFacts`, `sourceRevision.kind == "GIT"`, `authoritySetStatus == "CLEAN_FOR_AUTHORITY_SET"`, and `sourceRevision.head == batchBaseCommit`.
3. Require request, snapshot, and envelope project IDs to match.
4. Recompute `dependencyGraphDigest` from the normalized descriptors and compare it to the request.
5. Read the seven exact `controlled_planning.*` facts listed in the locked request contract. Each fact must be a dictionary whose `owner` is the envelope issuer ID, `sourcePath` is its issuer authority reference, and `normalizedValue` is a string; compare all seven values exactly to the normalized request, including canonical JSON text for the descriptor digest array.
6. Index snapshot authorities by path. Require the envelope issuer ID/reference/digest to match one authority record (`issuerAuthorityDigest == "sha256:" + record["sha256"]`) and every descriptor `authorityReferences` entry to appear in that index.
7. Parse `asOf`, `issuedAt`, and `expiresAt` with `datetime.fromisoformat(value.replace("Z", "+00:00"))` only to reject invalid or naive values; require `issuedAt < expiresAt`, and retain their original canonical strings in the normalized request.

Do not reread the project, Git, or authority source files in Phase 1A. The authority snapshot is the frozen input; exact binding prevents a caller from swapping in a self-consistent descriptor or envelope that the snapshot did not authorize.

- [ ] **Step 5: Run Task 1 tests to verify GREEN**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_controlled_inputs.py tests/test_schema_identity.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add core/schemas/controlled-*.schema.json \
  src/evolution_harness/controlled_inputs.py \
  tests/conftest.py \
  tests/test_controlled_inputs.py
git commit -m "feat: validate controlled planning inputs"
```

### Task 2: Deterministic conflict graph and conservative isolation

**Files:**

- Create: `src/evolution_harness/controlled_conflicts.py`
- Create: `tests/test_controlled_conflicts.py`

**Interfaces:**

- Consumes: normalized `controlled-slice-descriptor/v1` dictionaries from Task 1.
- Produces `build_conflict_report(repository_root: Path, *, project_id: str, authority_snapshot_fingerprint: str, conflict_policy_version: str, descriptors: list[dict[str, Any]]) -> dict[str, Any]`.

- Conflict reason codes: `SAME_OWNER`, `FACT_FAMILY_OVERLAP`, `BINDING_OVERLAP`, `EXACT_WRITESET_OVERLAP`, `EPHEMERAL_WRITESET_OVERLAP`, `SHARED_ARTIFACT_OVERLAP`, `AUTHORITY_INPUT_WRITE`, `DEPENDENCY_PATH`, `PRODUCER_CONSUMER_PATH`, `PUBLIC_CONTRACT_SERIAL_BARRIER`, `MIGRATION_SERIAL_BARRIER`, and `GLOBAL_SHARED_ARTIFACT_BARRIER`.

- [ ] **Step 1: Write the conflict-matrix tests**

Add explicit tests, each with two or three descriptors and exact reason assertions:

```python
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


def test_disjoint_cross_owner_slices_have_distinct_clusters(repository_root, controlled_factory):
    report = build_conflict_report(
        repository_root,
        project_id="neutral-project",
        authority_snapshot_fingerprint="sha256:" + "9" * 64,
        conflict_policy_version="controlled-conflict-policy/v1",
        descriptors=[
            controlled_factory.descriptor(sliceId="slice:a", ownerSet=["owner:a"], factFamilySet=["fact:a"], exactWriteSet=["a/src"], ephemeralWriteSet=["build/a"]),
            controlled_factory.descriptor(sliceId="slice:b", ownerSet=["owner:b"], factFamilySet=["fact:b"], exactWriteSet=["b/src"], ephemeralWriteSet=["build/b"]),
        ],
    )
    assert report["edges"] == []
    assert [item["sliceIds"] for item in report["clusters"]] == [["slice:a"], ["slice:b"]]


@pytest.mark.parametrize(
    ("left", "right", "reason"),
    [
        ({"ownerSet": ["owner:a"]}, {"ownerSet": ["owner:a"]}, "SAME_OWNER"),
        ({"factFamilySet": ["fact:x"]}, {"factFamilySet": ["fact:x"]}, "FACT_FAMILY_OVERLAP"),
        ({"exactWriteSet": ["services/a"]}, {"exactWriteSet": ["services/a/App.java"]}, "EXACT_WRITESET_OVERLAP"),
        ({"ephemeralWriteSet": ["build/shared"]}, {"exactWriteSet": ["build/shared/output"]}, "EPHEMERAL_WRITESET_OVERLAP"),
        ({"bindingSet": ["binding:x"]}, {"bindingSet": ["binding:x"]}, "BINDING_OVERLAP"),
        ({"sharedArtifactSet": ["generated:index"]}, {"sharedArtifactSet": ["generated:index"]}, "SHARED_ARTIFACT_OVERLAP"),
    ],
)
def test_overlap_reason_matrix(repository_root, controlled_factory, left, right, reason):
    first = controlled_factory.descriptor(sliceId="slice:a", **left)
    second = controlled_factory.descriptor(sliceId="slice:b", **right)
    report = _report(repository_root, controlled_factory, [first, second])
    assert len(report["edges"]) == 1
    assert report["edges"][0]["leftSliceId"] == "slice:a"
    assert report["edges"][0]["rightSliceId"] == "slice:b"
    assert reason in report["edges"][0]["reasons"]
```

Implement `test_overlap_reason_matrix` by applying `left` to `slice:a`, `right` to `slice:b`, building one report, and asserting that the single edge has `leftSliceId == "slice:a"`, `rightSliceId == "slice:b"`, and contains `reason`.

Add four more concrete tests:

- `test_public_contract_migration_and_global_artifact_are_serial_barriers`: create one descriptor for each barrier type plus a disjoint ordinary descriptor; assert each barrier descriptor has an edge to the ordinary descriptor with its exact barrier reason.
- `test_transitive_dependency_path_conflicts`: use `slice:a -> slice:b -> slice:c`; assert the `slice:a`/`slice:c` edge contains `DEPENDENCY_PATH`.
- `test_direct_and_transitive_producer_consumer_path_conflicts`: declare `owner:a -> owner:b` and `owner:b -> owner:c`; assert both the direct `slice:a`/`slice:b` edge and transitive `slice:a`/`slice:c` edge contain `PRODUCER_CONSUMER_PATH`.
- `test_writing_another_slice_authority_reference_conflicts`: write `authority/slice-b.yaml` from `slice:a` and use that path in `slice:b.authorityReferences`; assert `AUTHORITY_INPUT_WRITE`.
- `test_input_order_does_not_change_report_or_ids`: reverse descriptors and all set-valued inputs, then assert byte-equivalent `canonical_json_bytes(report)`.

Import and use `normalize_slice_descriptor` in every direct report test; `build_conflict_report` deliberately consumes normalized descriptors and is not a second input-admission path.

- [ ] **Step 2: Run the focused tests to verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_controlled_conflicts.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: evolution_harness.controlled_conflicts`.

- [ ] **Step 3: Implement path overlap, graph closure, and stable IDs**

Create pure helpers and the public builder:

```python
def _path_overlaps(left: str, right: str) -> bool:
    left_parts = PurePosixPath(left).parts
    right_parts = PurePosixPath(right).parts
    size = min(len(left_parts), len(right_parts))
    return left_parts[:size] == right_parts[:size]


def _stable_id(prefix: str, payload: Any) -> str:
    return f"{prefix}:" + sha256_bytes(canonical_json_bytes(payload))[:24]


def _transitive_closure(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    closure = {node: set(edges) for node, edges in graph.items()}
    for pivot in sorted(graph):
        for source in sorted(graph):
            if pivot in closure[source]:
                closure[source].update(closure[pivot])
    return closure
```

Rules are symmetric for scheduling. Build a dependency graph from each descriptor's `sliceId -> dependencySet` and an Owner graph from every `{producer, consumer}` record across the complete descriptor set. Compute full transitive closure for both graphs. Two Slices receive `DEPENDENCY_PATH` when either Slice ID reaches the other; they receive `PRODUCER_CONSUMER_PATH` when any Owner in one `ownerSet` reaches any Owner in the other, in either direction. Never infer graph edges from names or filesystem layout.

Sort each edge's Slice IDs, sort and deduplicate reason codes, then build connected components including singleton Slices. `conflictFootprintId` hashes project ID, policy version, and all normalized Owner, fact-family, contract, producer-consumer, binding, exact/ephemeral write, shared-artifact, dependency, migration, and authority-reference fields for that Slice; it excludes batch/snapshot identity. Compare exact writes to exact writes for `EXACT_WRITESET_OVERLAP`; compare every pair where at least one side is ephemeral for `EPHEMERAL_WRITESET_OVERLAP`. Check authority-input writes using both exact and ephemeral writes with component-aware path ancestry. Validate the completed report with `controlled-conflict-report.schema.json`.

Treat any non-empty `publicContractSet` or `migrationResourceSet`, and any `sharedArtifactSet` value beginning with `global:`, as a barrier that conflicts with every other descriptor. This is the conservative policy-v1 interpretation; do not add semantic inference.

- [ ] **Step 4: Run Task 2 tests to verify GREEN**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_controlled_inputs.py tests/test_controlled_conflicts.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/evolution_harness/controlled_conflicts.py \
  tests/test_controlled_conflicts.py
git commit -m "feat: calculate controlled planning conflicts"
```

### Task 3: Authorization decision and provisional scheduling

**Files:**

- Create: `src/evolution_harness/controlled_planner.py`
- Create: `tests/test_controlled_planner.py`

**Interfaces:**

- Consumes `normalize_planning_request`, `parse_rfc3339`, and `exact_writeset_digest` from Task 1, plus `build_conflict_report` from Task 2.
- Produces `build_authorization_decision(repository_root: Path, request: dict[str, Any]) -> dict[str, Any]` and `build_provisional_execution_plan(repository_root: Path, request: dict[str, Any]) -> dict[str, Any]`. The latter returns exactly `conflictReport`, `authorizationDecision`, and `executionPlan`.

- Authorization rejection codes: `ENVELOPE_NOT_YET_VALID`, `ENVELOPE_EXPIRED`, `PORTFOLIO_NOT_PERMITTED`, `DELIVERY_TRACK_NOT_PERMITTED`, `SLICE_CLASS_NOT_PERMITTED`, `ACTION_CLASS_NOT_PERMITTED`, `ACTION_EXPLICITLY_DENIED`, `WRITESET_OUTSIDE_PREFIX`, and `SLICE_NOT_READY`.
- Scheduling block/queue codes: `UNKNOWN_DEPENDENCY`, `DEPENDENCY_CYCLE`, `DEPENDENCY_NOT_CLOSED`, `CONFLICT_CLUSTER_BUSY`, and `PROJECT_CAPACITY_LIMIT`.

- [ ] **Step 1: Write authorization and plan-selection tests**

Cover every acceptance branch with exact outputs:

```python
def test_three_disjoint_ready_slices_are_proposed_in_deterministic_order(repository_root, controlled_factory):
    descriptors = [
        controlled_factory.descriptor(sliceId="slice:priority-1-b", priority=1, ownerSet=["owner:b"], factFamilySet=["fact:b"], exactWriteSet=["services/b"], ephemeralWriteSet=["build/b"]),
        controlled_factory.descriptor(sliceId="slice:priority-0", priority=0, ownerSet=["owner:a"], factFamilySet=["fact:a"], exactWriteSet=["services/a"], ephemeralWriteSet=["build/a"]),
        controlled_factory.descriptor(sliceId="slice:priority-1-a", priority=1, ownerSet=["owner:c"], factFamilySet=["fact:c"], exactWriteSet=["services/c"], ephemeralWriteSet=["build/c"]),
    ]
    result = build_provisional_execution_plan(
        repository_root,
        controlled_factory.request(*descriptors),
    )
    plan = result["executionPlan"]
    assert plan["provisional"] is True
    assert plan["requiresCoordinatorRecheck"] is True
    assert [item["sliceId"] for item in plan["proposedAdmissions"]] == [
        "slice:priority-0", "slice:priority-1-a", "slice:priority-1-b"
    ]


```

Add the following tests with these exact assertions:

- `test_fourth_disjoint_slice_is_queued_by_project_capacity`: four disjoint READY Slices under a cap of three; assert three proposed and the fourth queued with `PROJECT_CAPACITY_LIMIT`.
- `test_only_one_ready_slice_per_conflict_cluster_is_proposed`: two same-Owner READY Slices; assert the higher-priority Slice is proposed and the other queued with `CONFLICT_CLUSTER_BUSY`.
- `test_open_dependency_blocks_dependent_slice`: a READY Slice depends on a non-CLOSED Slice; assert it is blocked with `DEPENDENCY_NOT_CLOSED`.
- `test_unknown_dependency_fails_closed`: reference an absent Slice ID and assert `ControlledPlanningError.code == "UNKNOWN_DEPENDENCY"`.
- `test_dependency_cycle_fails_closed`: declare `slice:a -> slice:b -> slice:a` and assert `ControlledPlanningError.code == "DEPENDENCY_CYCLE"`.
- `test_expired_or_not_yet_valid_envelope_proposes_nothing`: parameterize `asOf` before issue and at expiry; assert no proposed admissions and authorization gate `NO_GO`.
- `test_track_class_action_denial_and_path_prefix_denials_are_explained`: mutate each authorization dimension independently, including an `authorizationClass` present in both permitted and denied action sets, and assert its exact rejection code.
- `test_every_output_validates_against_its_schema`: call `SchemaStore.validate` for all three result objects.
- `test_execution_requirements_preserve_envelope_and_slice_obligations`: give two proposed Slices distinct ordered gates and reviewer roles; assert the aggregate first-occurrence order and the exact per-Slice requirement records.
- `test_stop_conditions_are_preserved_as_mandatory_recheck_inputs`: assert the normalized envelope stop set is copied exactly and does not claim to have been evaluated by Phase 1A.
- `test_shuffled_equivalent_request_produces_identical_ids`: reverse descriptors and set inputs while retaining gate order; assert identical report, decision, and plan IDs.
- `test_as_of_and_envelope_are_bound_to_decision_and_plan_identity`: build two otherwise equal valid requests with different `asOf`, then with a separately authority-bound envelope, and assert the decision and plan IDs change while the conflict report ID remains stable.
- `test_existing_serial_resolution_is_unchanged_without_a_planning_request`: call `resolve_design_context` for `examples/project-fixture` with the established resolver request and assert the same selected capability IDs; do not create an automatic planning discovery path.

- [ ] **Step 2: Run the focused tests to verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_controlled_planner.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: evolution_harness.controlled_planner`.

- [ ] **Step 3: Implement authorization decisions**

Use only normalized values and explicit `asOf`:

```python
def _contains_path(prefix: str, path: str) -> bool:
    prefix_parts = PurePosixPath(prefix).parts
    path_parts = PurePosixPath(path).parts
    return path_parts[: len(prefix_parts)] == prefix_parts


def _authorization_reasons(descriptor: dict[str, Any], envelope: dict[str, Any], as_of: datetime) -> list[str]:
    reasons: list[str] = []
    if as_of < parse_rfc3339(envelope["issuedAt"]):
        reasons.append("ENVELOPE_NOT_YET_VALID")
    if as_of >= parse_rfc3339(envelope["expiresAt"]):
        reasons.append("ENVELOPE_EXPIRED")
    if descriptor["portfolioId"] != envelope["portfolioId"]:
        reasons.append("PORTFOLIO_NOT_PERMITTED")
    if descriptor["deliveryTrackId"] not in envelope["permittedDeliveryTracks"]:
        reasons.append("DELIVERY_TRACK_NOT_PERMITTED")
    if descriptor["sliceClass"] not in envelope["permittedSliceClasses"]:
        reasons.append("SLICE_CLASS_NOT_PERMITTED")
    if descriptor["authorizationClass"] not in envelope["permittedActionClasses"]:
        reasons.append("ACTION_CLASS_NOT_PERMITTED")
    if descriptor["authorizationClass"] in envelope["deniedActions"]:
        reasons.append("ACTION_EXPLICITLY_DENIED")
    declared_writes = descriptor["exactWriteSet"] + descriptor["ephemeralWriteSet"]
    if any(not any(_contains_path(prefix, path) for prefix in envelope["permittedPathPrefixes"])
           for path in declared_writes):
        reasons.append("WRITESET_OUTSIDE_PREFIX")
    if descriptor["state"] != "READY":
        reasons.append("SLICE_NOT_READY")
    return sorted(reasons)
```

The decision `gate` is `NO_GO` if the envelope is not yet valid or has expired, otherwise `PASS`; structurally invalid envelopes fail before a decision exists, and individual denied Slices remain explicit `REJECT` entries. Hash the complete decision excluding its ID, then validate the output schema.

- [ ] **Step 4: Implement dependency validation and plan selection**

After request normalization and before conflict construction, build a complete Slice index. Unknown dependency IDs and cycles raise `ControlledPlanningError` with the exact codes above. A READY Slice is blocked until all dependencies are `CLOSED`.

Eligible candidates are authorization `ALLOW` plus closed dependencies. Sort by `(priority ascending, dependencyDepth ascending, sliceId ascending)`. Walk that order, select at most one per conflict cluster and at most `min(envelope.maxParallelLanes, 3)`. Remaining eligible candidates enter `queued` with `CONFLICT_CLUSTER_BUSY` or `PROJECT_CAPACITY_LIMIT`; non-READY/dependency-gated candidates enter `blocked`; authorization denials enter `rejected`.

Populate the source bindings and per-admission digests before computing identity:

```python
plan.update({
    "batchBaseCommit": request["batchBaseCommit"],
    "authoritySnapshotFingerprint": request["authoritySnapshot"]["snapshotFingerprint"],
    "contractRegistryDigest": request["contractRegistryDigest"],
    "dependencyGraphDigest": request["dependencyGraphDigest"],
    "authorizationEnvelopeDigest": request["authorizationEnvelope"]["envelopeDigest"],
    "conflictPolicyVersion": request["conflictPolicyVersion"],
    "harnessVersion": request["harnessVersion"],
    "asOf": request["asOf"],
    "proposedAdmissions": [
        {
            "sliceId": item["sliceId"],
            "conflictClusterId": cluster_by_slice[item["sliceId"]],
            "descriptorDigest": item["descriptorDigest"],
            "exactWriteSetDigest": exact_writeset_digest(item),
        }
        for item in sorted(proposed_descriptors, key=lambda item: item["sliceId"])
    ],
})
plan["batchPlanId"] = _stable_id(
    "batch-plan",
    {key: value for key, value in plan.items() if key != "batchPlanId"},
)
```

Validate the authorization decision, conflict report, and execution plan immediately before return. Never write them to disk.

Build `executionPlan.executionRequirements` without losing Slice-level obligations. Start `requiredGates` with the envelope's declared order, then visit proposed Slices by `sliceId` and append each descriptor gate on first occurrence. `requiredReviewers` is the sorted union of the envelope list and every proposed descriptor's `reviewPolicy.reviewerRole`; `requiredTests` remains the normalized envelope set; `minimumReviewVerdict` is the envelope value. Add one sorted `sliceRequirements` record per proposed Slice, preserving that descriptor's gate order and complete review policy. Copy `stopConditions` into `mandatoryStopConditions`. This makes all minimum execution obligations visible without claiming Phase 1A can run or satisfy them.

- [ ] **Step 5: Run Task 3 tests to verify GREEN**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_controlled_inputs.py \
  tests/test_controlled_conflicts.py \
  tests/test_controlled_planner.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/evolution_harness/controlled_planner.py \
  tests/test_controlled_planner.py
git commit -m "feat: build provisional controlled execution plans"
```

### Task 4: Read-only CLI, compatibility evidence, and repository documentation

**Files:**

- Modify: `src/evolution_harness/cli.py:10-30,90-137,140-305`
- Create: `tests/test_controlled_planning_cli.py`
- Modify: `README.md:170-207,218-229`

**Interfaces:**

- Consumes: `load_planning_request(repository_root, request_path)` and `build_provisional_execution_plan(repository_root, request)`.
- Produces one read-only command:

```text
harness planning plan --request <path> [--format text|json]
```

- JSON continues using the existing outer `harness-cli/v1` envelope. Planner errors expose their stable `ControlledPlanningError.code`; schema errors continue through the existing failure wrapper.

- [ ] **Step 1: Write CLI contract and no-write tests**

Create a request file in `tmp_path`, snapshot the repository and request directories before invocation, and call the module through a subprocess:

```python
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


def _copy_schema_root(tmp_path):
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    shutil.copytree(source / "core", root / "core")
    return root


def _tree_bytes(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _run_cli(root, *args):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    return subprocess.run(
        [sys.executable, "-m", "evolution_harness.cli", "--repository-root", str(root), *args],
        text=True,
        capture_output=True,
        env=environment,
    )


def test_planning_cli_emits_deterministic_read_only_json(tmp_path, controlled_factory):
    root = _copy_schema_root(tmp_path)
    request_path = tmp_path / "controlled-request.yaml"
    request_path.write_text(
        yaml.safe_dump(controlled_factory.request(controlled_factory.descriptor()), sort_keys=False),
        encoding="utf-8",
    )
    before = _tree_bytes(root)
    request_before = request_path.read_bytes()
    result = _run_cli(root, "planning", "plan", "--request", str(request_path), "--format", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schemaVersion"] == "harness-cli/v1"
    assert payload["command"] == "planning plan"
    assert payload["data"]["executionPlan"]["provisional"] is True
    assert payload["data"]["executionPlan"]["requiresCoordinatorRecheck"] is True
    assert before == _tree_bytes(root)
    assert request_before == request_path.read_bytes()


```

Add three exact negative/compatibility cases:

- `test_planning_cli_rejects_partial_descriptor_without_writes`: delete `bindingSet`, invoke the CLI, assert exit 1, `ok is False`, error message contains `bindingSet`, and before/after tree bytes match.
- `test_planning_cli_rejects_snapshot_fingerprint_drift`: replace the fingerprint with 64 zeroes, assert exit 1 and error code `AUTHORITY_SNAPSHOT_FINGERPRINT_MISMATCH`.
- `test_existing_validate_and_resolve_cli_contracts_are_unchanged`: invoke `validate --format json` and the established `resolve --project <fixture> --intent architecture-review --topic resolver-mvp --output 'review findings' --runtime CHATGPT --format json` request; assert both exit 0 and keep `harness-cli/v1` envelopes.

- [ ] **Step 2: Run the CLI tests to verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_controlled_planning_cli.py -q
```

Expected: FAIL because `planning` is not yet a recognized command.

- [ ] **Step 3: Wire the CLI without adding persistence**

Add imports and parser/dispatch only:

```python
from .controlled_inputs import load_planning_request
from .controlled_planner import build_provisional_execution_plan

# build_parser()
p = sub.add_parser("planning")
s = p.add_subparsers(dest="action", required=True)
q = s.add_parser("plan")
q.add_argument("--request", required=True)
_add_format(q)

# main()
if args.command == "planning" and args.action == "plan":
    request = load_planning_request(root, Path(args.request))
    return _emit(
        build_provisional_execution_plan(root, request),
        fmt=fmt,
        command=command,
    )
```

Do not add `--apply`, `--persist`, discovery from a project, coordinator state, or output-directory arguments.

- [ ] **Step 4: Document the command and explicit limits**

Add `harness planning plan --request <file>` to the CLI block. In “Deliberate MVP limits”, state:

```text
Controlled planning is a deterministic Phase 1A projection only. It validates
explicit authority-backed descriptors and emits a provisional plan to stdout.
It does not discover missing concurrency facts, admit work, create worktrees,
acquire leases, execute Slices, integrate commits, or write a registered project.
Projects without the controlled model retain their existing serial flow.
```

- [ ] **Step 5: Run focused and compatibility tests to verify GREEN**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_controlled_inputs.py \
  tests/test_controlled_conflicts.py \
  tests/test_controlled_planner.py \
  tests/test_controlled_planning_cli.py \
  tests/test_assurance_cli.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/evolution_harness/cli.py \
  tests/test_controlled_planning_cli.py \
  README.md
git commit -m "feat: expose read-only controlled planning"
```

## Final Phase 1A Verification and Fixed-Candidate Gate

- [ ] **Step 1: Run formatting and placeholder checks**

```bash
git diff --check ababefb..HEAD
rg -n 'TB[D]|TO[D]O|FIXM[E]|PLACEHOLDE[R]' \
  core/schemas/controlled-*.schema.json \
  src/evolution_harness/controlled_*.py \
  tests/conftest.py \
  tests/test_controlled_*.py \
  README.md
```

Expected: both commands produce no findings.

- [ ] **Step 2: Run all Harness acceptance gates with Python 3.12**

```bash
export PATH=/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin:$PATH
./harness validate --check-generated --format json
./harness registry build --check --format json
./harness catalog build --check --format json
./harness project lock --project examples/project-fixture --check --format json
./harness projection build --project examples/project-fixture \
  --intent architecture-review --topic resolver-mvp \
  --output 'review findings' --runtime CHATGPT --check --format json
./harness projection build --project examples/project-fixture \
  --intent architecture-review --topic resolver-mvp \
  --output 'review findings' --runtime CODEX --check --format json
./eng doctor --ci --json
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

Expected: every command exits 0; structural gate is `PASS` with `issues=[]`; both projections are fresh; engineering doctor is `PASS`; pytest reports zero failures.

- [ ] **Step 3: Verify the exact candidate boundary**

```bash
git status --short --branch
git diff --name-status ababefb..HEAD
git diff --check ababefb..HEAD
git rev-parse HEAD^
git rev-parse HEAD
git rev-parse 'HEAD^{tree}'
```

Expected: clean feature branch; only the approved Phase 0 design, this plan, and Phase 1A files are in the branch delta. Record Candidate, Parent, Tree, and exact WriteSet.

- [ ] **Step 4: Obtain independent fixed-candidate review**

Use the repository-prescribed fixed-candidate reviewer in a fresh detached clone. Require explicit review of:

```text
determinism; schema strictness; digest coverage; path-boundary validation;
conflict completeness; transitive graph behavior; authorization expiry;
priority/capacity ordering; legacy serial non-regression; read-only CLI;
Phase 1B/1C exclusion; Pay-Nexus neutrality; P0/P1/P2 counts.
```

Release Phase 1B planning only after `GO / P0=0 / P1=0 / P2=0` on the exact fixed candidate.
