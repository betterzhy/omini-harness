from __future__ import annotations

import copy
import re
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
_DESCRIPTOR_SCHEMA = "core/schemas/controlled-slice-descriptor.schema.json"
_ENVELOPE_SCHEMA = "core/schemas/controlled-authorization-envelope.schema.json"
_REQUEST_SCHEMA = "core/schemas/controlled-planning-request.schema.json"
_RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_FACT_IDS = (
    "controlled_planning.mode",
    "controlled_planning.batch_base_commit",
    "controlled_planning.contract_registry_digest",
    "controlled_planning.dependency_graph_digest",
    "controlled_planning.authorization_envelope_digest",
    "controlled_planning.slice_descriptor_digests",
    "controlled_planning.conflict_policy_version",
)


class ControlledPlanningError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _sha256(payload: Any) -> str:
    return "sha256:" + sha256_bytes(canonical_json_bytes(payload))


def _safe_path(value: str, label: str) -> str:
    try:
        return safe_relative_path(value, label=label).as_posix()
    except PathBoundaryError as exc:
        raise ControlledPlanningError("UNSAFE_DECLARED_PATH", str(exc)) from exc


def _normalize_descriptor_fields(descriptor: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(descriptor)
    for field in SET_FIELDS:
        if field not in PATH_FIELDS:
            payload[field] = sorted(payload[field])
    payload["producerConsumerSet"] = sorted(
        payload["producerConsumerSet"], key=lambda item: (item["producer"], item["consumer"])
    )
    for field in PATH_FIELDS:
        payload[field] = sorted(_safe_path(path, field) for path in payload[field])
    return payload


def _normalize_envelope_fields(envelope: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(envelope)
    for field in ENVELOPE_SET_FIELDS:
        if field != "permittedPathPrefixes":
            payload[field] = sorted(payload[field])
    payload["issuerAuthorityReference"] = _safe_path(
        payload["issuerAuthorityReference"], "issuerAuthorityReference"
    )
    payload["permittedPathPrefixes"] = sorted(
        _safe_path(path, "permittedPathPrefixes") for path in payload["permittedPathPrefixes"]
    )
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
    if not isinstance(value, str) or _RFC3339_PATTERN.fullmatch(value) is None:
        raise ControlledPlanningError("TIMESTAMP_INVALID", f"invalid RFC 3339 timestamp: {value}")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except (TypeError, ValueError) as exc:
        raise ControlledPlanningError("TIMESTAMP_INVALID", f"invalid timestamp: {value}") from exc
    if parsed.utcoffset() is None:
        raise ControlledPlanningError("TIMESTAMP_INVALID", f"timestamp must include an offset: {value}")
    return parsed


def normalize_slice_descriptor(repository_root: Path, value: dict[str, Any]) -> dict[str, Any]:
    store = SchemaStore(repository_root)
    store.validate(_DESCRIPTOR_SCHEMA, value)
    normalized = _normalize_descriptor_fields(value)
    store.validate(_DESCRIPTOR_SCHEMA, normalized)
    if descriptor_digest(normalized) != normalized["descriptorDigest"]:
        raise ControlledPlanningError("DIGEST_MISMATCH", "descriptor digest does not match normalized descriptor")
    return normalized


def normalize_authorization_envelope(repository_root: Path, value: dict[str, Any]) -> dict[str, Any]:
    store = SchemaStore(repository_root)
    store.validate(_ENVELOPE_SCHEMA, value)
    normalized = _normalize_envelope_fields(value)
    store.validate(_ENVELOPE_SCHEMA, normalized)
    if envelope_digest(normalized) != normalized["envelopeDigest"]:
        raise ControlledPlanningError("DIGEST_MISMATCH", "envelope digest does not match normalized envelope")
    return normalized


def _validate_snapshot(
    snapshot: dict[str, Any], batch_base_commit: str
) -> dict[str, dict[str, Any]]:
    fingerprint = _sha256({key: value for key, value in snapshot.items() if key != "snapshotFingerprint"})
    if snapshot["snapshotFingerprint"] != fingerprint:
        raise ControlledPlanningError("AUTHORITY_SNAPSHOT_FINGERPRINT_MISMATCH", "snapshot fingerprint mismatch")
    revision = snapshot["sourceRevision"]
    expected_set_digest = _sha256(snapshot["authorities"])
    if revision["authoritySetDigest"] != expected_set_digest:
        raise ControlledPlanningError("AUTHORITY_SET_DIGEST_MISMATCH", "authority set digest mismatch")
    authority_ids = [record["id"] for record in snapshot["authorities"]]
    canonical_authority_paths = [
        _safe_path(record["path"], "authoritySnapshot.authorities.path")
        for record in snapshot["authorities"]
    ]
    if len(authority_ids) != len(set(authority_ids)) or len(
        canonical_authority_paths
    ) != len(set(canonical_authority_paths)):
        raise ControlledPlanningError("AUTHORITY_RECORD_DUPLICATE", "authority records must have unique IDs and paths")
    if snapshot["gate"] != "PASS" or snapshot["conflicts"] or snapshot["missingFacts"]:
        raise ControlledPlanningError("AUTHORITY_SNAPSHOT_NO_GO", "authority snapshot is not an unconflicted PASS")
    if revision["kind"] != "GIT" or revision["authoritySetStatus"] != "CLEAN_FOR_AUTHORITY_SET":
        raise ControlledPlanningError("AUTHORITY_SOURCE_NOT_CLEAN_GIT", "authority snapshot is not a clean Git authority set")
    if revision["head"] != batch_base_commit:
        raise ControlledPlanningError("BATCH_BASE_MISMATCH", "batch base commit differs from authority snapshot head")
    return {
        canonical_path: record
        for canonical_path, record in zip(
            canonical_authority_paths, snapshot["authorities"], strict=True
        )
    }


def _validate_authority_facts(request: dict[str, Any], descriptors: list[dict[str, Any]], envelope: dict[str, Any]) -> None:
    snapshot = request["authoritySnapshot"]
    expected = {
        "controlled_planning.mode": request["planningMode"],
        "controlled_planning.batch_base_commit": request["batchBaseCommit"],
        "controlled_planning.contract_registry_digest": request["contractRegistryDigest"],
        "controlled_planning.dependency_graph_digest": request["dependencyGraphDigest"],
        "controlled_planning.authorization_envelope_digest": envelope["envelopeDigest"],
        "controlled_planning.slice_descriptor_digests": canonical_json_bytes(
            sorted(item["descriptorDigest"] for item in descriptors)
        ).decode("utf-8"),
        "controlled_planning.conflict_policy_version": request["conflictPolicyVersion"],
    }
    for fact_id in _FACT_IDS:
        fact = snapshot["facts"].get(fact_id)
        if not isinstance(fact, dict):
            raise ControlledPlanningError("AUTHORITY_FACT_MISSING", f"authority fact missing: {fact_id}")
        source_path = fact.get("sourcePath")
        if not isinstance(source_path, str):
            raise ControlledPlanningError("AUTHORITY_FACT_MISMATCH", f"authority fact source path mismatch: {fact_id}")
        canonical_source_path = _safe_path(
            source_path, f"authoritySnapshot.facts.{fact_id}.sourcePath"
        )
        if (
            fact.get("owner") != envelope["issuerId"]
            or canonical_source_path != envelope["issuerAuthorityReference"]
            or not isinstance(fact.get("normalizedValue"), str)
            or fact["normalizedValue"] != expected[fact_id]
        ):
            raise ControlledPlanningError("AUTHORITY_FACT_MISMATCH", f"authority fact mismatch: {fact_id}")


def _validate_authority_references(
    authorities_by_path: dict[str, dict[str, Any]],
    descriptors: list[dict[str, Any]],
    envelope: dict[str, Any],
) -> None:
    issuer = authorities_by_path.get(envelope["issuerAuthorityReference"])
    if (
        issuer is None
        or issuer["id"] != envelope["issuerId"]
        or envelope["issuerAuthorityDigest"] != "sha256:" + issuer["sha256"]
    ):
        raise ControlledPlanningError("AUTHORITY_REFERENCE_UNBOUND", "authorization envelope issuer is not bound to snapshot")
    for descriptor in descriptors:
        for reference in descriptor["authorityReferences"]:
            if reference not in authorities_by_path:
                raise ControlledPlanningError("AUTHORITY_REFERENCE_UNBOUND", f"unbound descriptor authority reference: {reference}")


def normalize_planning_request(repository_root: Path, value: dict[str, Any]) -> dict[str, Any]:
    store = SchemaStore(repository_root)
    store.validate(_REQUEST_SCHEMA, value)
    raw_slice_ids = [item["sliceId"] for item in value["slices"]]
    if len(raw_slice_ids) != len(set(raw_slice_ids)):
        raise ControlledPlanningError("DUPLICATE_SLICE_ID", "slice IDs must be unique")
    descriptors = [normalize_slice_descriptor(repository_root, item) for item in value["slices"]]
    envelope = normalize_authorization_envelope(repository_root, value["authorizationEnvelope"])
    normalized = copy.deepcopy(value)
    normalized["slices"] = descriptors
    normalized["authorizationEnvelope"] = envelope
    authorities_by_path = _validate_snapshot(
        normalized["authoritySnapshot"], normalized["batchBaseCommit"]
    )
    if (
        normalized["projectId"] != normalized["authoritySnapshot"]["projectId"]
        or normalized["projectId"] != envelope["projectId"]
    ):
        raise ControlledPlanningError("PROJECT_ID_MISMATCH", "request, snapshot, and envelope project IDs must match")
    if dependency_graph_digest(descriptors) != normalized["dependencyGraphDigest"]:
        raise ControlledPlanningError("DEPENDENCY_GRAPH_DIGEST_MISMATCH", "dependency graph digest mismatch")
    _validate_authority_facts(normalized, descriptors, envelope)
    _validate_authority_references(authorities_by_path, descriptors, envelope)
    as_of = parse_rfc3339(normalized["asOf"])
    issued_at = parse_rfc3339(envelope["issuedAt"])
    expires_at = parse_rfc3339(envelope["expiresAt"])
    if issued_at >= expires_at:
        raise ControlledPlanningError("AUTHORIZATION_INTERVAL_INVALID", "authorization interval must be positive")
    del as_of
    store.validate(_REQUEST_SCHEMA, normalized)
    return normalized


def load_planning_request(repository_root: Path, path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ControlledPlanningError("DIGEST_MISMATCH", "planning request must be a mapping")
    return normalize_planning_request(repository_root, loaded)
