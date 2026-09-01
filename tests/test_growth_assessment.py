from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from evolution_harness.schema import SchemaStore, SchemaValidationError


REQUEST_SCHEMA = "core/schemas/growth-assessment-request.schema.json"
RECEIPT_SCHEMA = "core/schemas/growth-assessment-receipt.schema.json"
CAPTURE_SCHEMA = "core/schemas/growth-capture-result.schema.json"
SCAN_SCHEMA = "core/schemas/growth-scan-report.schema.json"


def _repository_root() -> Path:
    return Path(__file__).parents[1]


def _validate(schema_path: str, value: dict) -> None:
    SchemaStore(_repository_root()).validate(schema_path, value)


def _assert_invalid(schema_path: str, value: dict) -> None:
    with pytest.raises(SchemaValidationError):
        _validate(schema_path, value)


def _registered_source(*, width: int = 40) -> dict:
    return {
        "sourceKind": "REGISTERED_PROJECT",
        "projectId": "neutral-project",
        "integrationId": "neutral-shadow",
        "runtime": "CODEX",
        "sourceRevision": {
            "kind": "GIT",
            "head": "a" * width,
            "tree": "b" * width,
        },
        "authoritySnapshotFingerprint": "sha256:" + "c" * 64,
        "capabilityLockFingerprint": "sha256:" + "d" * 64,
    }


def _harness_source(*, width: int = 40) -> dict:
    return {
        "sourceKind": "HARNESS_SELF",
        "projectId": "agent-evolution-harness",
        "runtime": "CHATGPT",
        "sourceRevision": {
            "kind": "GIT",
            "head": "1" * width,
            "tree": "2" * width,
        },
    }


def _task(*, with_candidate: bool = False, width: int = 40) -> dict:
    value = {
        "taskId": "task:neutral-1",
        "attemptId": "attempt:neutral-1",
        "gateId": "gate:review",
    }
    if with_candidate:
        value.update(
            {
                "candidate": "3" * width,
                "parent": "4" * width,
                "tree": "5" * width,
            }
        )
    return value


def _evidence(*, availability: str = "REPLAYABLE") -> dict:
    return {
        "kind": "FIXED_REVIEW",
        "reference": (
            "reports/fixed-review.json"
            if availability == "REPLAYABLE"
            else "review://neutral/fixed-candidate"
        ),
        "revision": "review-revision-1",
        "digest": "sha256:" + "6" * 64,
        "availability": availability,
        "visibility": "PROJECT",
        "distillation": "Independent review found no blocking issue.",
    }


def _r1_signal_request() -> dict:
    return {
        "schemaVersion": "growth-assessment-request/v1",
        "policyVersion": "growth-assessment-policy/v1",
        "source": _registered_source(),
        "task": _task(),
        "riskLevel": "R1",
        "trigger": "HUMAN_CORRECTION",
        "projectGate": "PASS",
        "verdict": "SIGNAL",
        "reasonCodes": ["REUSABLE_AGENT_BEHAVIOR"],
        "summary": "A reusable review behavior was identified.",
        "impact": "The behavior can prevent repeated authority mistakes.",
        "capabilityHints": ["skill:agent-design:architecture-review"],
        "evidence": [_evidence()],
        "assessedAt": "2026-09-01T12:30:45Z",
    }


def _r2_no_signal_request(*, width: int = 40) -> dict:
    return {
        "schemaVersion": "growth-assessment-request/v1",
        "policyVersion": "growth-assessment-policy/v1",
        "source": _harness_source(width=width),
        "task": _task(with_candidate=True, width=width),
        "riskLevel": "R2",
        "trigger": "FIXED_CANDIDATE_REVIEW",
        "projectGate": "PASS",
        "verdict": "NO_SIGNAL",
        "reasonCodes": ["ACCIDENTAL"],
        "summary": "The observation was accidental and not reusable.",
        "impact": "",
        "capabilityHints": [],
        "evidence": [],
        "assessedAt": "2026-09-01T12:30:45.123+08:00",
    }


def _receipt(*, status: str = "RECORDED") -> dict:
    return {
        "schemaVersion": "growth-assessment-receipt/v1",
        "policyVersion": "growth-assessment-policy/v1",
        "assessmentKey": "growth-key:" + "7" * 24,
        "assessmentId": "growth-assessment:" + "8" * 24,
        "requestDigest": "sha256:" + "9" * 64,
        "status": status,
        "growthCaptureGate": "PASS",
        "assessment": _r1_signal_request(),
    }


def _capture_pass(*, status: str = "RECORDED") -> dict:
    receipt = _receipt(status=status)
    return {
        "schemaVersion": "growth-capture-result/v1",
        "growthCaptureGate": "PASS",
        "status": status,
        "assessmentKey": receipt["assessmentKey"],
        "assessmentId": receipt["assessmentId"],
        "requestDigest": receipt["requestDigest"],
        "receipt": receipt,
    }


def _capture_deferred() -> dict:
    return {
        "schemaVersion": "growth-capture-result/v1",
        "growthCaptureGate": "DEFERRED",
        "status": "DEFERRED",
        "assessmentKey": "growth-key:" + "7" * 24,
        "assessmentId": "growth-assessment:" + "8" * 24,
        "requestDigest": "sha256:" + "9" * 64,
        "deferredReason": "INBOX_LOCKED",
        "retryInstruction": {
            "command": "growth assess",
            "requiresSameRequestDigest": True,
            "requiresSameSourceContext": True,
        },
    }


def _valid_scan_record(*, verdict: str = "SIGNAL") -> dict:
    signal = verdict == "SIGNAL"
    return {
        "assessmentKey": "growth-key:" + "7" * 24,
        "assessmentId": "growth-assessment:" + "8" * 24,
        "requestDigest": "sha256:" + "9" * 64,
        "projectId": "neutral-project",
        "sourceKind": "REGISTERED_PROJECT",
        "riskLevel": "R1",
        "trigger": "HUMAN_CORRECTION",
        "verdict": verdict,
        "visibilityCeiling": "PROJECT" if signal else "NONE",
        "capabilityHints": ["skill:agent-design:architecture-review"],
        "disposition": "HUMAN_TRIAGE_REQUIRED" if signal else "NO_ACTION",
    }


def _scan_report(*, valid: bool = True) -> dict:
    records = (
        [_valid_scan_record()]
        if valid
        else [
            {
                "entryNameDigest": "sha256:" + "a" * 64,
                "errorCode": "RECEIPT_CORRUPT",
                "disposition": "INVALID_RECEIPT",
            }
        ]
    )
    return {
        "schemaVersion": "growth-scan-report/v1",
        "policyVersion": "growth-assessment-policy/v1",
        "asOf": "2026-09-01T13:00:00Z",
        "stateRootIdentity": "sha256:" + "b" * 64,
        "records": records,
        "counts": {
            "totalEntries": 1,
            "validRecords": 1 if valid else 0,
            "invalidRecords": 0 if valid else 1,
            "signal": 1 if valid else 0,
            "noSignal": 0,
            "humanTriageRequired": 1 if valid else 0,
            "noAction": 0,
        },
        "gate": "PASS" if valid else "FAIL",
    }


@pytest.mark.parametrize(
    ("schema_path", "factory"),
    [
        (REQUEST_SCHEMA, _r1_signal_request),
        (REQUEST_SCHEMA, _r2_no_signal_request),
        (RECEIPT_SCHEMA, _receipt),
        (CAPTURE_SCHEMA, _capture_pass),
        (CAPTURE_SCHEMA, _capture_deferred),
        (SCAN_SCHEMA, _scan_report),
        (SCAN_SCHEMA, lambda: _scan_report(valid=False)),
    ],
)
def test_valid_protocol_documents_are_accepted(schema_path, factory):
    _validate(schema_path, factory())


@pytest.mark.parametrize("field", list(_r1_signal_request()))
def test_request_rejects_each_missing_required_top_level_field(field):
    value = _r1_signal_request()
    del value[field]
    _assert_invalid(REQUEST_SCHEMA, value)


@pytest.mark.parametrize(
    "field", ["transcript", "messages", "prompt", "response", "rawLog", "fileContent"]
)
def test_request_rejects_raw_or_unknown_top_level_fields(field):
    value = _r1_signal_request()
    value[field] = "forbidden raw content"
    _assert_invalid(REQUEST_SCHEMA, value)


def test_request_source_branches_are_closed_and_mode_specific():
    registered = _r1_signal_request()
    del registered["source"]["capabilityLockFingerprint"]
    _assert_invalid(REQUEST_SCHEMA, registered)

    harness = _r2_no_signal_request()
    harness["source"]["integrationId"] = "not-allowed"
    _assert_invalid(REQUEST_SCHEMA, harness)


@pytest.mark.parametrize("width", [40, 64])
def test_request_accepts_uniform_git_object_formats(width):
    _validate(REQUEST_SCHEMA, _r2_no_signal_request(width=width))


def test_request_rejects_mixed_source_and_candidate_git_formats():
    source_mixed = _r1_signal_request()
    source_mixed["source"]["sourceRevision"]["tree"] = "b" * 64
    _assert_invalid(REQUEST_SCHEMA, source_mixed)

    candidate_mixed = _r2_no_signal_request()
    candidate_mixed["task"]["tree"] = "5" * 64
    _assert_invalid(REQUEST_SCHEMA, candidate_mixed)


@pytest.mark.parametrize("field", ["candidate", "parent", "tree"])
def test_request_rejects_partial_candidate_tuple(field):
    value = _r2_no_signal_request()
    del value["task"][field]
    _assert_invalid(REQUEST_SCHEMA, value)


@pytest.mark.parametrize(
    "reference", ["", "/absolute", ".", "..", "a//b", "a\\b", "a/./b", "a/../b"]
)
def test_replayable_evidence_rejects_unsafe_references(reference):
    value = _r1_signal_request()
    value["evidence"][0]["reference"] = reference
    _assert_invalid(REQUEST_SCHEMA, value)


@pytest.mark.parametrize("reference", ["/absolute", "\\absolute", "C:\\absolute", ".", ".."])
def test_opaque_evidence_rejects_path_like_references(reference):
    value = _r1_signal_request()
    value["evidence"] = [_evidence(availability="OPAQUE")]
    value["evidence"][0]["reference"] = reference
    _assert_invalid(REQUEST_SCHEMA, value)


def test_opaque_evidence_accepts_uri_like_identifier():
    value = _r1_signal_request()
    value["evidence"] = [_evidence(availability="OPAQUE")]
    _validate(REQUEST_SCHEMA, value)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("summary",), "x" * 2001),
        (("impact",), "x" * 2001),
        (("evidence", 0, "distillation"), "x" * 1001),
        (("evidence", 0, "reference"), "x" * 513),
        (("evidence", 0, "revision"), "x" * 129),
    ],
)
def test_request_rejects_text_over_transport_bounds(path, replacement):
    value = _r1_signal_request()
    target = value
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = replacement
    _assert_invalid(REQUEST_SCHEMA, value)


@pytest.mark.parametrize("field", ["reasonCodes", "capabilityHints", "evidence"])
def test_request_rejects_duplicate_set_items(field):
    value = _r1_signal_request()
    value[field].append(copy.deepcopy(value[field][0]))
    _assert_invalid(REQUEST_SCHEMA, value)


@pytest.mark.parametrize("field", ["summary", "impact", "evidence"])
def test_signal_requires_summary_impact_and_evidence(field):
    value = _r1_signal_request()
    value[field] = [] if field == "evidence" else ""
    _assert_invalid(REQUEST_SCHEMA, value)


def test_signal_and_no_signal_reason_sets_never_mix():
    signal = _r1_signal_request()
    signal["reasonCodes"] = ["ACCIDENTAL"]
    _assert_invalid(REQUEST_SCHEMA, signal)

    no_signal = _r2_no_signal_request()
    no_signal["reasonCodes"] = ["CAPABILITY_GAP"]
    _assert_invalid(REQUEST_SCHEMA, no_signal)


def test_accidental_is_accepted_only_for_no_signal():
    _validate(REQUEST_SCHEMA, _r2_no_signal_request())
    value = _r1_signal_request()
    value["reasonCodes"] = ["ACCIDENTAL"]
    _assert_invalid(REQUEST_SCHEMA, value)


def test_risk_specific_trigger_sets_do_not_cross():
    r1 = _r1_signal_request()
    r1["trigger"] = "FORMAL_CLOSURE"
    _assert_invalid(REQUEST_SCHEMA, r1)

    r2 = _r2_no_signal_request()
    r2["trigger"] = "HUMAN_CORRECTION"
    _assert_invalid(REQUEST_SCHEMA, r2)


def test_capability_hints_use_the_canonical_colon_qualified_pattern():
    _validate(REQUEST_SCHEMA, _r1_signal_request())
    value = _r1_signal_request()
    value["capabilityHints"] = ["architecture-review"]
    _assert_invalid(REQUEST_SCHEMA, value)


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-09-01T12:30:45",
        "2026-09-01 12:30:45Z",
        "2026-09-01T12:30:45+24:00",
        "2026-09-01T12:30:45+08:60",
    ],
)
def test_request_rejects_malformed_rfc3339_shapes(timestamp):
    value = _r1_signal_request()
    value["assessedAt"] = timestamp
    _assert_invalid(REQUEST_SCHEMA, value)


def test_request_rejects_malformed_digest_and_git_identity():
    value = _r1_signal_request()
    value["source"]["authoritySnapshotFingerprint"] = "sha256:short"
    _assert_invalid(REQUEST_SCHEMA, value)

    value = _r1_signal_request()
    value["source"]["sourceRevision"]["head"] = "A" * 40
    _assert_invalid(REQUEST_SCHEMA, value)


@pytest.mark.parametrize("field", list(_receipt()))
def test_receipt_rejects_each_missing_required_field(field):
    value = _receipt()
    del value[field]
    _assert_invalid(RECEIPT_SCHEMA, value)


def test_receipt_rejects_unknown_fields_and_invalid_status_gate():
    value = _receipt()
    value["rawRequest"] = {}
    _assert_invalid(RECEIPT_SCHEMA, value)

    value = _receipt()
    value["status"] = "DEFERRED"
    _assert_invalid(RECEIPT_SCHEMA, value)

    value = _receipt()
    value["growthCaptureGate"] = "FAIL"
    _assert_invalid(RECEIPT_SCHEMA, value)


@pytest.mark.parametrize("field", list(_capture_pass()))
def test_pass_capture_rejects_each_missing_field(field):
    value = _capture_pass()
    del value[field]
    _assert_invalid(CAPTURE_SCHEMA, value)


def test_capture_result_closes_pass_and_deferred_branches():
    value = _capture_pass()
    value["deferredReason"] = "INBOX_LOCKED"
    _assert_invalid(CAPTURE_SCHEMA, value)

    value = _capture_deferred()
    value["receipt"] = _receipt()
    _assert_invalid(CAPTURE_SCHEMA, value)

    value = _capture_deferred()
    value["deferredReason"] = "STATE_ROOT_UNSAFE"
    _assert_invalid(CAPTURE_SCHEMA, value)

    value = _capture_deferred()
    value["retryInstruction"]["command"] = "growth scan"
    _assert_invalid(CAPTURE_SCHEMA, value)


@pytest.mark.parametrize(
    ("outer_status", "receipt_status"),
    [("RECORDED", "DUPLICATE"), ("DUPLICATE", "RECORDED")],
)
def test_capture_pass_status_matches_receipt_status(outer_status, receipt_status):
    value = _capture_pass(status=outer_status)
    value["receipt"]["status"] = receipt_status
    _assert_invalid(CAPTURE_SCHEMA, value)


@pytest.mark.parametrize("field", list(_scan_report()))
def test_scan_report_rejects_each_missing_top_level_field(field):
    value = _scan_report()
    del value[field]
    _assert_invalid(SCAN_SCHEMA, value)


@pytest.mark.parametrize("field", list(_scan_report()["counts"]))
def test_scan_report_requires_every_count(field):
    value = _scan_report()
    del value["counts"][field]
    _assert_invalid(SCAN_SCHEMA, value)


def test_scan_report_closes_valid_and_invalid_record_branches():
    value = _scan_report()
    value["records"][0]["summary"] = "must not be exposed"
    _assert_invalid(SCAN_SCHEMA, value)

    value = _scan_report(valid=False)
    value["records"][0]["assessmentId"] = "growth-assessment:" + "8" * 24
    _assert_invalid(SCAN_SCHEMA, value)


@pytest.mark.parametrize(
    ("verdict", "disposition"),
    [("SIGNAL", "NO_ACTION"), ("NO_SIGNAL", "HUMAN_TRIAGE_REQUIRED")],
)
def test_scan_record_enforces_verdict_disposition_pairing(verdict, disposition):
    value = _scan_report()
    value["records"][0]["verdict"] = verdict
    value["records"][0]["disposition"] = disposition
    _assert_invalid(SCAN_SCHEMA, value)


def test_scan_report_rejects_unknown_fields_and_out_of_range_counts():
    value = _scan_report()
    value["absoluteStateRoot"] = "/private/state"
    _assert_invalid(SCAN_SCHEMA, value)

    value = _scan_report()
    value["counts"]["totalEntries"] = 10001
    _assert_invalid(SCAN_SCHEMA, value)


def test_scan_report_accepts_empty_pass_observation():
    value = _scan_report()
    value["records"] = []
    value["counts"] = {field: 0 for field in value["counts"]}
    _validate(SCAN_SCHEMA, value)


@pytest.mark.parametrize(
    ("schema_path", "schema_id"),
    [
        (REQUEST_SCHEMA, "https://agent-evolution.local/core/schemas/growth-assessment-request.schema.json"),
        (RECEIPT_SCHEMA, "https://agent-evolution.local/core/schemas/growth-assessment-receipt.schema.json"),
        (CAPTURE_SCHEMA, "https://agent-evolution.local/core/schemas/growth-capture-result.schema.json"),
        (SCAN_SCHEMA, "https://agent-evolution.local/core/schemas/growth-scan-report.schema.json"),
    ],
)
def test_protocol_schemas_publish_the_fixed_dialect_and_identity(schema_path, schema_id):
    schema = json.loads((_repository_root() / schema_path).read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == schema_id


@pytest.mark.parametrize("status", ["RECORDED", "DUPLICATE"])
def test_receipt_and_pass_capture_accept_both_transport_statuses(status):
    _validate(RECEIPT_SCHEMA, _receipt(status=status))
    _validate(CAPTURE_SCHEMA, _capture_pass(status=status))


@pytest.mark.parametrize("reason", ["STATE_ROOT_UNAVAILABLE", "INBOX_LOCKED"])
def test_deferred_capture_accepts_exactly_the_two_retryable_reasons(reason):
    value = _capture_deferred()
    value["deferredReason"] = reason
    _validate(CAPTURE_SCHEMA, value)


def test_capture_result_has_no_fail_branch():
    value = {
        "schemaVersion": "growth-capture-result/v1",
        "growthCaptureGate": "FAIL",
        "status": "FAIL",
        "assessmentKey": "growth-key:" + "7" * 24,
        "assessmentId": "growth-assessment:" + "8" * 24,
        "requestDigest": "sha256:" + "9" * 64,
    }
    _assert_invalid(CAPTURE_SCHEMA, value)


def test_scan_accepts_no_signal_no_action_record():
    value = _scan_report()
    value["records"] = [_valid_scan_record(verdict="NO_SIGNAL")]
    value["counts"].update(
        {
            "signal": 0,
            "noSignal": 1,
            "humanTriageRequired": 0,
            "noAction": 1,
        }
    )
    _validate(SCAN_SCHEMA, value)


@pytest.mark.parametrize("error_code", ["RECEIPT_UNSAFE", "RECEIPT_CORRUPT"])
def test_scan_accepts_both_invalid_record_error_codes(error_code):
    value = _scan_report(valid=False)
    value["records"][0]["errorCode"] = error_code
    _validate(SCAN_SCHEMA, value)


@pytest.mark.parametrize(
    "trigger",
    [
        "HUMAN_CORRECTION",
        "REPEATED_FRICTION",
        "SHARED_GUIDANCE_CONFLICT",
        "CONTRACT_AMBIGUITY",
        "VERIFICATION_GAP",
    ],
)
def test_scan_accepts_each_r1_trigger(trigger):
    value = _scan_report()
    value["records"][0]["trigger"] = trigger
    _validate(SCAN_SCHEMA, value)


@pytest.mark.parametrize(
    "trigger",
    [
        "FORMAL_CLOSURE",
        "FIXED_CANDIDATE_REVIEW",
        "GATE_FAILURE",
        "AUTHORITY_OR_GOVERNANCE_CHANGE",
        "SECURITY_RECOVERY_OR_CONCURRENCY_FINDING",
        "CONTRACT_SCHEMA_OR_PROJECTION_CHANGE",
    ],
)
def test_scan_accepts_each_r2_trigger(trigger):
    value = _scan_report()
    value["records"][0]["riskLevel"] = "R2"
    value["records"][0]["trigger"] = trigger
    _validate(SCAN_SCHEMA, value)


@pytest.mark.parametrize(
    ("risk_level", "trigger"),
    [("R1", "FORMAL_CLOSURE"), ("R2", "HUMAN_CORRECTION")],
)
def test_scan_rejects_cross_risk_triggers(risk_level, trigger):
    value = _scan_report()
    value["records"][0]["riskLevel"] = risk_level
    value["records"][0]["trigger"] = trigger
    _assert_invalid(SCAN_SCHEMA, value)


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-09-01T13:00:00",
        "2026-09-01 13:00:00Z",
        "2026-09-01T13:00:00+24:00",
        "2026-09-01T13:00:00+08:60",
    ],
)
def test_scan_rejects_malformed_rfc3339_shapes(timestamp):
    value = _scan_report()
    value["asOf"] = timestamp
    _assert_invalid(SCAN_SCHEMA, value)


def test_scan_capability_hints_repeat_the_canonical_constraint():
    _validate(SCAN_SCHEMA, _scan_report())
    value = _scan_report()
    value["records"][0]["capabilityHints"] = ["architecture-review"]
    _assert_invalid(SCAN_SCHEMA, value)


def test_scan_records_are_unique():
    value = _scan_report()
    value["records"].append(copy.deepcopy(value["records"][0]))
    _assert_invalid(SCAN_SCHEMA, value)


def _invalid_scan_records(count: int) -> list[dict]:
    return [
        {
            "entryNameDigest": "sha256:" + f"{index:064x}",
            "errorCode": "RECEIPT_CORRUPT",
            "disposition": "INVALID_RECEIPT",
        }
        for index in range(count)
    ]


def test_scan_records_accept_the_10000_entry_schema_boundary():
    value = _scan_report(valid=False)
    value["records"] = _invalid_scan_records(10000)
    _validate(SCAN_SCHEMA, value)


def test_scan_records_reject_the_10001st_entry():
    value = _scan_report(valid=False)
    value["records"] = _invalid_scan_records(10001)
    _assert_invalid(SCAN_SCHEMA, value)


@pytest.mark.parametrize("field", list(_scan_report()["counts"]))
def test_scan_count_fields_enforce_the_10000_boundary(field):
    value = _scan_report()
    value["counts"][field] = 10000
    _validate(SCAN_SCHEMA, value)

    value["counts"][field] = 10001
    _assert_invalid(SCAN_SCHEMA, value)


@pytest.mark.parametrize("field", list(_registered_source()))
def test_registered_source_requires_each_declared_field(field):
    value = _r1_signal_request()
    del value["source"][field]
    _assert_invalid(REQUEST_SCHEMA, value)


@pytest.mark.parametrize("field", list(_harness_source()))
def test_harness_source_requires_each_declared_field(field):
    value = _r2_no_signal_request()
    del value["source"][field]
    _assert_invalid(REQUEST_SCHEMA, value)


@pytest.mark.parametrize("field", list(_task()))
def test_task_without_candidate_requires_each_declared_field(field):
    value = _r1_signal_request()
    del value["task"][field]
    _assert_invalid(REQUEST_SCHEMA, value)


@pytest.mark.parametrize("field", list(_evidence()))
def test_evidence_requires_each_declared_field(field):
    value = _r1_signal_request()
    del value["evidence"][0][field]
    _assert_invalid(REQUEST_SCHEMA, value)


@pytest.mark.parametrize("field", list(_capture_deferred()["retryInstruction"]))
def test_retry_instruction_requires_each_declared_field(field):
    value = _capture_deferred()
    del value["retryInstruction"][field]
    _assert_invalid(CAPTURE_SCHEMA, value)


@pytest.mark.parametrize("field", list(_capture_deferred()))
def test_deferred_capture_requires_each_declared_field(field):
    value = _capture_deferred()
    del value[field]
    _assert_invalid(CAPTURE_SCHEMA, value)


@pytest.mark.parametrize("field", list(_valid_scan_record()))
def test_valid_scan_record_requires_each_declared_field(field):
    value = _scan_report()
    del value["records"][0][field]
    _assert_invalid(SCAN_SCHEMA, value)


@pytest.mark.parametrize("field", list(_scan_report(valid=False)["records"][0]))
def test_invalid_scan_record_requires_each_declared_field(field):
    value = _scan_report(valid=False)
    del value["records"][0][field]
    _assert_invalid(SCAN_SCHEMA, value)


@pytest.mark.parametrize(
    ("factory", "path"),
    [
        (_r1_signal_request, ("source",)),
        (_r1_signal_request, ("task",)),
        (_r1_signal_request, ("evidence", 0)),
        (_capture_deferred, ("retryInstruction",)),
        (_scan_report, ("counts",)),
        (_scan_report, ("records", 0)),
    ],
)
def test_nested_protocol_objects_reject_unknown_fields(factory, path):
    value = factory()
    target = value
    for part in path:
        target = target[part]
    target["unknownField"] = True
    schema_path = REQUEST_SCHEMA
    if factory is _capture_deferred:
        schema_path = CAPTURE_SCHEMA
    elif factory is _scan_report:
        schema_path = SCAN_SCHEMA
    _assert_invalid(schema_path, value)
