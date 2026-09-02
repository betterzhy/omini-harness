from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .hashing import canonical_json_bytes, sha256_bytes
from .schema import SchemaStore, SchemaValidationError


GROWTH_POLICY_VERSION = "growth-assessment-policy/v1"

_REQUEST_SCHEMA = "core/schemas/growth-assessment-request.schema.json"
_RECEIPT_SCHEMA = "core/schemas/growth-assessment-receipt.schema.json"
_CAPTURE_SCHEMA = "core/schemas/growth-capture-result.schema.json"
_RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$"
)
_RFC3339_PARTS_PATTERN = re.compile(
    r"^(?P<second>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(?P<fraction>\d+))?(?P<offset>Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$"
)
_PROSE_FIELDS = frozenset({"summary", "impact", "distillation"})
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_RECEIPT_FIELDS = frozenset(
    {
        "schemaVersion",
        "policyVersion",
        "assessmentKey",
        "assessmentId",
        "requestDigest",
        "status",
        "growthCaptureGate",
        "assessment",
    }
)


class GrowthAssessmentError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _parse_rfc3339_parts(value: str) -> tuple[datetime, str]:
    if not isinstance(value, str) or _RFC3339_PATTERN.fullmatch(value) is None:
        raise GrowthAssessmentError("TIMESTAMP_INVALID", f"invalid RFC 3339 timestamp: {value}")
    match = _RFC3339_PARTS_PATTERN.fullmatch(value)
    assert match is not None
    try:
        offset = "+00:00" if match["offset"] == "Z" else match["offset"]
        parsed = datetime.fromisoformat(match["second"] + offset)
    except (TypeError, ValueError) as exc:
        raise GrowthAssessmentError("TIMESTAMP_INVALID", f"invalid RFC 3339 timestamp: {value}") from exc
    if parsed.utcoffset() is None:
        raise GrowthAssessmentError("TIMESTAMP_INVALID", f"timestamp must include an offset: {value}")
    return parsed.astimezone(timezone.utc), (match["fraction"] or "").rstrip("0")


def parse_rfc3339(value: str) -> datetime:
    """Parse an explicit RFC 3339 instant and return its UTC datetime."""
    parsed, fraction = _parse_rfc3339_parts(value)
    if not fraction:
        return parsed
    return parsed.replace(microsecond=int((fraction[:6] + "000000")[:6]))


def _rfc3339_order_key(value: str) -> tuple[datetime, str]:
    """Return an exact UTC ordering key without truncating fractional seconds."""
    return _parse_rfc3339_parts(value)


def _utc_rfc3339(value: str) -> str:
    parsed, fraction = _parse_rfc3339_parts(value)
    canonical = parsed.strftime("%Y-%m-%dT%H:%M:%S")
    return canonical + (f".{fraction}" if fraction else "") + "Z"


def _validate_schema(repository_root: Path, schema_path: str, value: Any, *, code: str) -> None:
    try:
        SchemaStore(repository_root).validate(schema_path, value)
    except (SchemaValidationError, FileNotFoundError) as exc:
        raise GrowthAssessmentError(code, f"schema validation failed: {exc}") from exc


def _reject_non_prose_controls(value: Any, *, field: str | None = None) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_non_prose_controls(item, field=key)
    elif isinstance(value, list):
        for item in value:
            _reject_non_prose_controls(item, field=field)
    elif isinstance(value, str) and field not in _PROSE_FIELDS:
        if "\r" in value or "\n" in value or _CONTROL_PATTERN.search(value):
            raise GrowthAssessmentError("GROWTH_ARGUMENT_INVALID", "control character in non-prose field")


def _normalize_prose(value: str, *, required: bool, label: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    if _CONTROL_PATTERN.search(normalized):
        raise GrowthAssessmentError("GROWTH_ARGUMENT_INVALID", f"control character in {label}")
    if required and not normalized.strip():
        raise GrowthAssessmentError("GROWTH_ARGUMENT_INVALID", f"{label} must contain non-whitespace text")
    return normalized


def _evidence_sort_key(item: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    return (
        item["kind"],
        item["reference"],
        item["revision"],
        item["digest"],
        item["availability"],
        item["visibility"],
        item["distillation"],
    )


def _keyed_evidence_identity(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return item["kind"], item["reference"], item["revision"], item["digest"]


def normalize_growth_assessment_request(repository_root: Path, value: dict[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize a request without inspecting project state."""
    _validate_schema(repository_root, _REQUEST_SCHEMA, value, code="ASSESSMENT_SCHEMA_INVALID")
    normalized = copy.deepcopy(value)
    _reject_non_prose_controls(normalized)

    normalized["summary"] = _normalize_prose(normalized["summary"], required=True, label="summary")
    normalized["impact"] = _normalize_prose(
        normalized["impact"], required=normalized["verdict"] == "SIGNAL", label="impact"
    )
    for evidence in normalized["evidence"]:
        evidence["distillation"] = _normalize_prose(
            evidence["distillation"], required=True, label="evidence distillation"
        )

    normalized["assessedAt"] = _utc_rfc3339(normalized["assessedAt"])
    keyed_evidence = [_keyed_evidence_identity(item) for item in normalized["evidence"]]
    if len(keyed_evidence) != len(set(keyed_evidence)):
        raise GrowthAssessmentError("GROWTH_ARGUMENT_INVALID", "duplicate keyed evidence identity")
    normalized["reasonCodes"] = sorted(normalized["reasonCodes"])
    normalized["capabilityHints"] = sorted(normalized["capabilityHints"])
    normalized["evidence"] = sorted(normalized["evidence"], key=_evidence_sort_key)
    _validate_schema(repository_root, _REQUEST_SCHEMA, normalized, code="ASSESSMENT_SCHEMA_INVALID")
    return normalized


def _key_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "policyVersion": value["policyVersion"],
        "source": value["source"],
        "task": value["task"],
    }


def growth_assessment_key(value: dict[str, Any]) -> str:
    return "growth-key:" + sha256_bytes(canonical_json_bytes(_key_payload(value)))[:24]


def growth_assessment_id(value: dict[str, Any]) -> str:
    return "growth-assessment:" + sha256_bytes(canonical_json_bytes(value))[:24]


def growth_request_digest(value: dict[str, Any]) -> str:
    return "sha256:" + sha256_bytes(canonical_json_bytes(value))


def build_growth_receipt(value: dict[str, Any]) -> dict[str, Any]:
    """Create the typed in-memory Receipt projection for a normalized request."""
    return {
        "schemaVersion": "growth-assessment-receipt/v1",
        "policyVersion": GROWTH_POLICY_VERSION,
        "assessmentKey": growth_assessment_key(value),
        "assessmentId": growth_assessment_id(value),
        "requestDigest": growth_request_digest(value),
        "status": "RECORDED",
        "growthCaptureGate": "PASS",
        "assessment": copy.deepcopy(value),
    }


def _verify_receipt_identities(receipt: dict[str, Any], normalized: dict[str, Any]) -> None:
    expected = {
        "assessmentKey": growth_assessment_key(normalized),
        "assessmentId": growth_assessment_id(normalized),
        "requestDigest": growth_request_digest(normalized),
    }
    for field, code in (
        ("assessmentKey", "ASSESSMENT_KEY_CONFLICT"),
        ("assessmentId", "ASSESSMENT_ID_MISMATCH"),
        ("requestDigest", "REQUEST_DIGEST_MISMATCH"),
    ):
        if receipt[field] != expected[field]:
            raise GrowthAssessmentError(code, f"receipt {field} does not match assessment")


def _validate_receipt_for_capture(value: dict[str, Any], receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_FIELDS:
        raise GrowthAssessmentError("GROWTH_ARGUMENT_INVALID", "receipt does not have the closed receipt shape")
    if receipt["schemaVersion"] != "growth-assessment-receipt/v1":
        raise GrowthAssessmentError("GROWTH_ARGUMENT_INVALID", "receipt schema version is invalid")
    if receipt["policyVersion"] != GROWTH_POLICY_VERSION:
        raise GrowthAssessmentError("GROWTH_ARGUMENT_INVALID", "receipt policy version is invalid")
    if receipt["status"] not in {"RECORDED", "DUPLICATE"}:
        raise GrowthAssessmentError("GROWTH_ARGUMENT_INVALID", "receipt status is invalid")
    if receipt["growthCaptureGate"] != "PASS":
        raise GrowthAssessmentError("GROWTH_ARGUMENT_INVALID", "receipt capture gate is invalid")
    if receipt["assessment"] != value:
        raise GrowthAssessmentError("ASSESSMENT_ID_MISMATCH", "receipt assessment does not match request")
    _verify_receipt_identities(receipt, value)
    return receipt


def validate_growth_receipt(repository_root: Path, value: dict[str, Any]) -> dict[str, Any]:
    """Revalidate a Receipt and all identities from its canonical assessment."""
    _validate_schema(repository_root, _RECEIPT_SCHEMA, value, code="RECEIPT_CORRUPT")
    if value["policyVersion"] != GROWTH_POLICY_VERSION:
        raise GrowthAssessmentError("RECEIPT_CORRUPT", "receipt policy version is not supported")
    try:
        normalized = normalize_growth_assessment_request(repository_root, value["assessment"])
    except GrowthAssessmentError as exc:
        raise GrowthAssessmentError("RECEIPT_CORRUPT", f"receipt assessment is invalid: {exc}") from exc
    if normalized != value["assessment"]:
        raise GrowthAssessmentError("RECEIPT_CORRUPT", "receipt assessment is not normalized")
    _verify_receipt_identities(value, normalized)
    return copy.deepcopy(value)


def build_growth_capture_result(
    value: dict[str, Any],
    *,
    receipt: dict[str, Any] | None = None,
    deferred_reason: str | None = None,
) -> dict[str, Any]:
    """Build the only two schema-valid capture result branches."""
    if (receipt is None) == (deferred_reason is None):
        raise GrowthAssessmentError("GROWTH_ARGUMENT_INVALID", "provide exactly one capture outcome")
    identities = {
        "assessmentKey": growth_assessment_key(value),
        "assessmentId": growth_assessment_id(value),
        "requestDigest": growth_request_digest(value),
    }
    if deferred_reason is not None:
        if deferred_reason not in {"STATE_ROOT_UNAVAILABLE", "INBOX_LOCKED"}:
            raise GrowthAssessmentError("GROWTH_ARGUMENT_INVALID", "deferred reason is not retryable")
        result = {
            "schemaVersion": "growth-capture-result/v1",
            "growthCaptureGate": "DEFERRED",
            "status": "DEFERRED",
            **identities,
            "deferredReason": deferred_reason,
            "retryInstruction": {
                "command": "growth assess",
                "requiresSameRequestDigest": True,
                "requiresSameSourceContext": True,
            },
        }
        return result

    assert receipt is not None
    _validate_receipt_for_capture(value, receipt)
    return {
        "schemaVersion": "growth-capture-result/v1",
        "growthCaptureGate": "PASS",
        "status": receipt["status"],
        **identities,
        "receipt": copy.deepcopy(receipt),
    }
