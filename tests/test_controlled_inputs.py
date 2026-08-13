from __future__ import annotations

import copy

import pytest

from evolution_harness.controlled_inputs import (
    ControlledPlanningError,
    dependency_graph_digest,
    descriptor_digest,
    envelope_digest,
    normalize_authorization_envelope,
    normalize_planning_request,
    normalize_slice_descriptor,
)
from evolution_harness.hashing import canonical_json_bytes, sha256_bytes
from evolution_harness.schema import SchemaValidationError


def _refresh_snapshot(snapshot):
    snapshot["snapshotFingerprint"] = "sha256:" + sha256_bytes(
        canonical_json_bytes({key: value for key, value in snapshot.items() if key != "snapshotFingerprint"})
    )


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
    request["authorizationEnvelope"]["envelopeDigest"] = envelope_digest(request["authorizationEnvelope"])
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


@pytest.mark.parametrize("kind,status", [("CONTENT", "CONTENT_SNAPSHOT"), ("GIT", "DIRTY_AUTHORITY_SET")])
def test_concurrent_planning_requires_clean_git_authority_snapshot(repository_root, controlled_factory, kind, status):
    request = controlled_factory.request(controlled_factory.descriptor())
    request["authoritySnapshot"]["sourceRevision"].update({"kind": kind, "authoritySetStatus": status})
    _refresh_snapshot(request["authoritySnapshot"])
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "AUTHORITY_SOURCE_NOT_CLEAN_GIT"


def test_authority_set_digest_mismatch_is_rejected(repository_root, controlled_factory):
    request = controlled_factory.request(controlled_factory.descriptor())
    request["authoritySnapshot"]["sourceRevision"]["authoritySetDigest"] = "sha256:" + "0" * 64
    _refresh_snapshot(request["authoritySnapshot"])
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "AUTHORITY_SET_DIGEST_MISMATCH"


@pytest.mark.parametrize("field", ["id", "path"])
def test_duplicate_authority_identity_is_rejected(repository_root, controlled_factory, field):
    request = controlled_factory.request(controlled_factory.descriptor())
    records = request["authoritySnapshot"]["authorities"]
    records.append(copy.deepcopy(records[0]))
    records[-1][field] = records[0][field]
    request["authoritySnapshot"]["sourceRevision"]["authoritySetDigest"] = "sha256:" + sha256_bytes(
        canonical_json_bytes(records)
    )
    _refresh_snapshot(request["authoritySnapshot"])
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "AUTHORITY_RECORD_DUPLICATE"


def test_missing_authority_fact_is_rejected(repository_root, controlled_factory):
    request = controlled_factory.request(controlled_factory.descriptor())
    del request["authoritySnapshot"]["facts"]["controlled_planning.mode"]
    _refresh_snapshot(request["authoritySnapshot"])
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "AUTHORITY_FACT_MISSING"


def test_non_string_authority_fact_is_rejected(repository_root, controlled_factory):
    request = controlled_factory.request(controlled_factory.descriptor())
    request["authoritySnapshot"]["facts"]["controlled_planning.mode"]["normalizedValue"] = 7
    _refresh_snapshot(request["authoritySnapshot"])
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "AUTHORITY_FACT_MISMATCH"


def test_batch_base_must_match_snapshot_head(repository_root, controlled_factory):
    request = controlled_factory.request(controlled_factory.descriptor(), batchBaseCommit="b" * 40)
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "BATCH_BASE_MISMATCH"


def test_graph_digest_must_match_canonical_descriptors(repository_root, controlled_factory):
    request = controlled_factory.request(controlled_factory.descriptor())
    request["dependencyGraphDigest"] = "sha256:" + "3" * 64
    request["authoritySnapshot"]["facts"]["controlled_planning.dependency_graph_digest"]["rawValue"] = request["dependencyGraphDigest"]
    request["authoritySnapshot"]["facts"]["controlled_planning.dependency_graph_digest"]["normalizedValue"] = request["dependencyGraphDigest"]
    _refresh_snapshot(request["authoritySnapshot"])
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "DEPENDENCY_GRAPH_DIGEST_MISMATCH"


def test_unbound_descriptor_authority_reference_is_rejected(repository_root, controlled_factory):
    request = controlled_factory.request(controlled_factory.descriptor())
    request["authoritySnapshot"]["authorities"] = request["authoritySnapshot"]["authorities"][:1]
    request["authoritySnapshot"]["sourceRevision"]["authoritySetDigest"] = "sha256:" + sha256_bytes(
        canonical_json_bytes(request["authoritySnapshot"]["authorities"])
    )
    _refresh_snapshot(request["authoritySnapshot"])
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "AUTHORITY_REFERENCE_UNBOUND"


def test_envelope_issuer_digest_must_match_authority_record(repository_root, controlled_factory):
    envelope = controlled_factory.envelope(issuerAuthorityDigest="sha256:" + "9" * 64)
    request = controlled_factory.request(controlled_factory.descriptor(), envelope=envelope)
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "AUTHORITY_REFERENCE_UNBOUND"


def test_authorization_interval_must_be_positive(repository_root, controlled_factory):
    envelope = controlled_factory.envelope(issuedAt="2026-08-14T00:00:00Z", expiresAt="2026-08-14T00:00:00Z")
    request = controlled_factory.request(controlled_factory.descriptor(), envelope=envelope)
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "AUTHORIZATION_INTERVAL_INVALID"


def test_normalizes_authorization_envelope_sets(repository_root, controlled_factory):
    envelope = controlled_factory.envelope(requiredReviewers=["reviewer:z", "reviewer:a"])
    normalized = normalize_authorization_envelope(repository_root, envelope)
    assert normalized["requiredReviewers"] == ["reviewer:a", "reviewer:z"]


def test_authority_paths_reject_traversal_even_when_snapshot_is_self_consistent(
    repository_root, controlled_factory
):
    request = controlled_factory.request(controlled_factory.descriptor())
    envelope = request["authorizationEnvelope"]
    envelope["issuerAuthorityReference"] = "../outside-authority.yaml"
    envelope["envelopeDigest"] = "sha256:" + "9" * 64
    snapshot = request["authoritySnapshot"]
    envelope_fact = snapshot["facts"]["controlled_planning.authorization_envelope_digest"]
    envelope_fact["rawValue"] = envelope["envelopeDigest"]
    envelope_fact["normalizedValue"] = envelope["envelopeDigest"]
    snapshot["authorities"][0]["path"] = envelope["issuerAuthorityReference"]
    for fact in snapshot["facts"].values():
        fact["sourcePath"] = envelope["issuerAuthorityReference"]
    snapshot["sourceRevision"]["authoritySetDigest"] = "sha256:" + sha256_bytes(
        canonical_json_bytes(snapshot["authorities"])
    )
    _refresh_snapshot(snapshot)
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "UNSAFE_DECLARED_PATH"


@pytest.mark.parametrize("path_target", ["authority-record", "fact-source"])
def test_snapshot_authority_paths_reject_traversal(repository_root, controlled_factory, path_target):
    request = controlled_factory.request(controlled_factory.descriptor())
    snapshot = request["authoritySnapshot"]
    if path_target == "authority-record":
        snapshot["authorities"][1]["path"] = "../outside-authority.yaml"
        snapshot["sourceRevision"]["authoritySetDigest"] = "sha256:" + sha256_bytes(
            canonical_json_bytes(snapshot["authorities"])
        )
    else:
        snapshot["facts"]["controlled_planning.mode"]["sourcePath"] = "../outside-authority.yaml"
    _refresh_snapshot(snapshot)
    with pytest.raises(ControlledPlanningError) as exc:
        normalize_planning_request(repository_root, request)
    assert exc.value.code == "UNSAFE_DECLARED_PATH"


def test_descriptor_paths_are_canonicalized_before_sorting_and_digesting(repository_root, controlled_factory):
    repeated_separator = controlled_factory.descriptor(exactWriteSet=["a//z", "a/b"])
    canonical = controlled_factory.descriptor(exactWriteSet=["a/b", "a/z"])
    normalized = normalize_slice_descriptor(repository_root, repeated_separator)
    assert normalized["exactWriteSet"] == ["a/b", "a/z"]
    assert descriptor_digest(repeated_separator) == descriptor_digest(canonical)


def test_envelope_prefixes_are_canonicalized_before_sorting_and_digesting(repository_root, controlled_factory):
    repeated_separator = controlled_factory.envelope(permittedPathPrefixes=["a//z", "a/b"])
    canonical = controlled_factory.envelope(permittedPathPrefixes=["a/b", "a/z"])
    normalized = normalize_authorization_envelope(repository_root, repeated_separator)
    assert normalized["permittedPathPrefixes"] == ["a/b", "a/z"]
    assert envelope_digest(repeated_separator) == envelope_digest(canonical)


def test_invalid_issuer_id_is_rejected_even_when_snapshot_binding_matches(repository_root, controlled_factory):
    request = controlled_factory.request(controlled_factory.descriptor())
    invalid_issuer = "INVALID ISSUER"
    envelope = request["authorizationEnvelope"]
    envelope["issuerId"] = invalid_issuer
    envelope["envelopeDigest"] = envelope_digest(envelope)
    snapshot = request["authoritySnapshot"]
    envelope_fact = snapshot["facts"]["controlled_planning.authorization_envelope_digest"]
    envelope_fact["rawValue"] = envelope["envelopeDigest"]
    envelope_fact["normalizedValue"] = envelope["envelopeDigest"]
    snapshot["authorities"][0]["id"] = invalid_issuer
    for fact in snapshot["facts"].values():
        fact["owner"] = invalid_issuer
    snapshot["sourceRevision"]["authoritySetDigest"] = "sha256:" + sha256_bytes(
        canonical_json_bytes(snapshot["authorities"])
    )
    _refresh_snapshot(snapshot)
    with pytest.raises(SchemaValidationError, match="issuerId"):
        normalize_planning_request(repository_root, request)


def test_request_project_id_requires_controlled_id_grammar(repository_root, controlled_factory):
    request = controlled_factory.request(controlled_factory.descriptor())
    request["projectId"] = "INVALID PROJECT"
    with pytest.raises(SchemaValidationError, match="projectId"):
        normalize_planning_request(repository_root, request)
