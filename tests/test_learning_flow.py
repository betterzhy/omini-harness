from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml


def _copy_repo(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    for name in ["core", "design"]:
        shutil.copytree(source / name, root / name)
    return root


def _source(reference: str = "chatgpt://project/fixture/conversation/1") -> dict:
    return {"sourceType": "CONVERSATION", "reference": reference, "visibility": "PRIVATE", "distillation": "Short source pointer only."}


def _experience(exp_id: str = "experience:agent-design:EXP001") -> dict:
    return {
        "schemaVersion": "experience/v1",
        "experienceId": exp_id,
        "source": _source(),
        "capturedAt": "2026-08-11T00:00:00Z",
        "designStage": "CALIBRATION",
        "signal": "Architecture review missed an authority boundary.",
        "observedBehavior": "Generic guidance was applied before project authority was checked.",
        "humanCorrection": "Resolve project authority first.",
        "impact": "Could reopen or override accepted design facts.",
        "triageStatus": "UNTRIAGED",
        "candidateHints": ["skill:agent-design:authority-gap-review"],
        "visibility": "PRIVATE",
    }


def _proposed_skill(version: str = "1.0.0", *, capability_id: str = "skill:agent-design:authority-gap-review", scope: dict | None = None) -> dict:
    return {
        "schemaVersion": "design-capability/v1",
        "id": capability_id,
        "kind": "SKILL",
        "version": version,
        "title": "Authority Gap Review",
        "summary": "Check project authority before reusable guidance.",
        "lifecycle": "ACTIVE",
        "validity": "VALID",
        "scope": scope or {"intent": ["architecture-review"], "stage": ["CALIBRATION"], "runtime": ["CHATGPT", "CODEX"], "domain": ["agent-design"]},
        "modelSensitivity": "MODEL_INDEPENDENT",
        "visibility": "SHARED",
        "provenance": [{"sourceType": "HUMAN_REVIEW", "reference": "candidate://authority-gap-review", "visibility": "SHARED"}],
        "relationships": {"dependsOn": ["principle:agent-design:project-truth-over-generic-guidance"], "extends": [], "derivedFrom": [], "supersedes": [], "constrainedBy": []},
        "evalBindings": [],
        "contentFile": "content.md",
        "skill": {
            "skillRole": "LEAF",
            "intent": ["architecture-review"],
            "triggers": ["authority ambiguity"],
            "whenNotToUse": [],
            "requiredContext": ["project authority references"],
            "referencedCapabilities": ["principle:agent-design:project-truth-over-generic-guidance"],
            "humanGates": ["architecture decision authority"],
            "outputContract": ["authority gaps"],
            "stopConditions": ["authority checked"],
            "selfReview": ["project truth wins"],
        },
    }


def _candidate(candidate_id: str = "candidate:agent-design:CAND001", *, status: str = "AUTHORIZED", decision: str = "APPROVE", operation: str = "CREATE", target: str = "skill:agent-design:authority-gap-review", eval_ids: list[str] | None = None, transfer: dict | None = None) -> dict:
    value = {
        "schemaVersion": "candidate/v1",
        "candidateId": candidate_id,
        "operation": operation,
        "targetCapability": target,
        "sourceExperiences": ["experience:agent-design:EXP001"],
        "scopeHypothesis": "Applicable to architecture review where project authority is explicit.",
        "expectedImprovement": "Prevent generic guidance from overriding project truth.",
        "evidence": [{"sourceType": "HUMAN_REVIEW", "reference": "review://candidate-1", "visibility": "SHARED"}],
        "counterexamples": ["No explicit project authority exists."],
        "evalRequirements": eval_ids or ["eval:agent-design:authority-gap-review"],
        "promotionStatus": status,
        "authorityDecision": decision,
    }
    if transfer is not None:
        value["transferEvidence"] = transfer
    return value


def _eval_definition(eval_id: str = "eval:agent-design:authority-gap-review", target: str = "skill:agent-design:authority-gap-review") -> dict:
    return {
        "schemaVersion": "design-eval/v1",
        "evalId": eval_id,
        "targetCapability": target,
        "scenario": "Review a project where generic guidance conflicts with explicit project authority.",
        "hiddenRisks": ["silent authority override"],
        "expectedReasoningCoverage": ["authority source", "conflict handling"],
        "expectedQuestions": ["Which artifact is authoritative?"],
        "forbiddenAssumptions": ["Shared guidance is automatically authoritative."],
        "criticalBoundaries": ["Project truth wins."],
        "acceptableAlternativeOutcomes": ["Escalate for human authority."],
        "regressionCriteria": ["Generic guidance silently overrides project truth."],
        "transferScope": ["agent-design"],
        "modelSensitivity": "MODEL_INDEPENDENT",
    }


def _write_eval(root: Path, definition: dict) -> None:
    path = root / "design/evals" / (definition["evalId"].replace(":", "_") + ".yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(definition, sort_keys=False), encoding="utf-8")


def test_experience_schema_rejects_full_conversation_transcript():
    from evolution_harness.schema import SchemaStore, SchemaValidationError

    root = Path(__file__).parents[1]
    value = _experience()
    value["messages"] = [{"role": "user", "content": "full transcript"}]
    with pytest.raises(SchemaValidationError):
        SchemaStore(root).validate("design/schemas/experience.schema.json", value)


def test_capture_experience_persists_opaque_source_reference_without_transcript(tmp_path: Path):
    from evolution_harness.learning import capture_experience

    root = _copy_repo(tmp_path)
    path = capture_experience(root, _experience())
    stored = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert stored["source"]["reference"].startswith("chatgpt://")
    assert "messages" not in stored
    assert "fullTranscript" not in stored["source"]


def test_experience_triage_is_explicit_and_persisted(tmp_path: Path):
    from evolution_harness.learning import capture_experience, triage_experience

    root = _copy_repo(tmp_path)
    capture_experience(root, _experience())
    updated = triage_experience(root, "experience:agent-design:EXP001", "CROSS_PROJECT_CANDIDATE")
    assert updated["triageStatus"] == "TRIAGED"
    assert updated["triageDecision"] == "CROSS_PROJECT_CANDIDATE"


def test_candidate_proposed_asset_reuses_normal_capability_schema(tmp_path: Path):
    from evolution_harness.learning import create_candidate

    root = _copy_repo(tmp_path)
    capture = root / "design/learning/experiences/exp.yaml"
    capture.parent.mkdir(parents=True, exist_ok=True)
    exp = _experience()
    exp["triageStatus"] = "TRIAGED"
    exp["triageDecision"] = "CROSS_PROJECT_CANDIDATE"
    capture.write_text(yaml.safe_dump(exp, sort_keys=False), encoding="utf-8")
    candidate_dir = create_candidate(root, _candidate(status="DRAFT", decision="PENDING"), _proposed_skill(), "# Authority Gap Review\n\nProcedure body.\n")
    assert (candidate_dir / "candidate.yaml").exists()
    assert (candidate_dir / "proposed/asset.yaml").exists()
    assert (candidate_dir / "proposed/content.md").exists()


def test_promotion_is_blocked_without_explicit_authority(tmp_path: Path):
    from evolution_harness.learning import LearningError, capture_experience, create_candidate, promote_candidate, triage_experience

    root = _copy_repo(tmp_path)
    capture_experience(root, _experience())
    triage_experience(root, "experience:agent-design:EXP001", "CROSS_PROJECT_CANDIDATE")
    create_candidate(root, _candidate(status="READY_FOR_REVIEW", decision="PENDING"), _proposed_skill(), "# Skill\n")
    with pytest.raises(LearningError) as exc:
        promote_candidate(root, "candidate:agent-design:CAND001", apply=True)
    assert exc.value.code == "AUTHORITY_REQUIRED"


def test_promotion_is_blocked_until_required_eval_passes(tmp_path: Path):
    from evolution_harness.learning import LearningError, capture_experience, create_candidate, promote_candidate, triage_experience

    root = _copy_repo(tmp_path)
    capture_experience(root, _experience())
    triage_experience(root, "experience:agent-design:EXP001", "CROSS_PROJECT_CANDIDATE")
    _write_eval(root, _eval_definition())
    create_candidate(root, _candidate(), _proposed_skill(), "# Skill\n")
    with pytest.raises(LearningError) as exc:
        promote_candidate(root, "candidate:agent-design:CAND001", apply=True)
    assert exc.value.code == "EVAL_REQUIRED"


def test_eval_result_records_capability_projection_runtime_and_model(tmp_path: Path):
    from evolution_harness.evals import record_eval_result

    root = _copy_repo(tmp_path)
    _write_eval(root, _eval_definition())
    result = {
        "schemaVersion": "eval-result/v1",
        "evalResultId": "eval-result:agent-design:RESULT001",
        "evalId": "eval:agent-design:authority-gap-review",
        "capabilityId": "skill:agent-design:authority-gap-review",
        "capabilityVersion": "1.0.0",
        "projectionVersion": "agent-skill-projection/1",
        "runtime": "CHATGPT",
        "model": "gpt-test",
        "executedAt": "2026-08-11T00:10:00Z",
        "result": "PASS",
        "evidence": ["manual://fixture-pass"],
    }
    path = record_eval_result(root, result)
    stored = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert (stored["capabilityId"], stored["capabilityVersion"]) == ("skill:agent-design:authority-gap-review", "1.0.0")
    assert (stored["projectionVersion"], stored["runtime"], stored["model"]) == ("agent-skill-projection/1", "CHATGPT", "gpt-test")


def test_authorized_candidate_with_passing_eval_promotes_new_canonical_version(tmp_path: Path):
    from evolution_harness.evals import record_eval_result
    from evolution_harness.learning import capture_experience, create_candidate, promote_candidate, triage_experience
    from evolution_harness.loader import load_capabilities

    root = _copy_repo(tmp_path)
    capture_experience(root, _experience())
    triage_experience(root, "experience:agent-design:EXP001", "CROSS_PROJECT_CANDIDATE")
    _write_eval(root, _eval_definition())
    record_eval_result(root, {
        "schemaVersion": "eval-result/v1", "evalResultId": "eval-result:agent-design:R1", "evalId": "eval:agent-design:authority-gap-review",
        "capabilityId": "skill:agent-design:authority-gap-review", "capabilityVersion": "1.0.0", "projectionVersion": "agent-skill-projection/1",
        "runtime": "CHATGPT", "model": "gpt-test", "executedAt": "2026-08-11T00:10:00Z", "result": "PASS", "evidence": ["manual://pass"]
    })
    create_candidate(root, _candidate(), _proposed_skill(), "# Authority Gap Review\n\nUse project authority first.\n")
    result = promote_candidate(root, "candidate:agent-design:CAND001", apply=True)
    assert result["applied"] is True
    promoted = [c for c in load_capabilities(root) if c.id == "skill:agent-design:authority-gap-review" and c.version == "1.0.0"]
    assert len(promoted) == 1
    ledger = yaml.safe_load((root / "core/governance/promotion-ledger.yaml").read_text(encoding="utf-8"))
    assert any(e["capabilityId"] == promoted[0].id and e["contentHash"] == promoted[0].content_hash for e in ledger["entries"])
    candidate = next(
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in (root / "design/learning/candidates").glob("*/candidate.yaml")
        if yaml.safe_load(path.read_text(encoding="utf-8"))["candidateId"] == "candidate:agent-design:CAND001"
    )
    assert candidate["promotionStatus"] == "INTEGRATED"


def test_broaden_scope_requires_transfer_evidence_and_transfer_eval(tmp_path: Path):
    from evolution_harness.learning import LearningError, capture_experience, create_candidate, promote_candidate, triage_experience

    root = _copy_repo(tmp_path)
    capture_experience(root, _experience())
    triage_experience(root, "experience:agent-design:EXP001", "CROSS_PROJECT_CANDIDATE")
    proposed = _proposed_skill(
        version="1.1.0",
        capability_id="skill:agent-design:architecture-review",
        scope={"intent": ["architecture-review"], "runtime": ["CHATGPT", "CODEX", "GENERIC_AGENT"], "domain": ["agent-design", "payment"]},
    )
    create_candidate(root, _candidate(operation="BROADEN_SCOPE", target="skill:agent-design:architecture-review"), proposed, "# Broadened architecture review\n")
    with pytest.raises(LearningError) as exc:
        promote_candidate(root, "candidate:agent-design:CAND001", apply=True)
    assert exc.value.code == "TRANSFER_EVIDENCE_REQUIRED"


def test_scope_broadening_must_be_monotonic():
    from evolution_harness.learning import is_monotonic_scope_broadening

    old = {"intent": ["architecture-review"], "stage": ["CALIBRATION"], "runtime": ["CHATGPT"], "domain": ["agent-design"]}
    broader = {"intent": ["architecture-review"], "runtime": ["CHATGPT", "CODEX"], "domain": ["agent-design", "payment"]}
    narrower = {"intent": ["architecture-review"], "stage": ["CALIBRATION"], "runtime": ["CHATGPT"], "domain": ["payment"]}
    assert is_monotonic_scope_broadening(old, broader)
    assert not is_monotonic_scope_broadening(old, narrower)


def test_bootstrap_learning_and_eval_fixtures_are_schema_valid():
    from evolution_harness.schema import SchemaStore

    root = Path(__file__).parents[1]
    store = SchemaStore(root)
    experiences = sorted((root / "design/learning/experiences").glob("*.yaml"))
    candidates = sorted((root / "design/learning/candidates").glob("*/candidate.yaml"))
    evals = sorted((root / "design/evals").glob("*.yaml"))
    assert len(experiences) >= 3
    assert len(candidates) >= 2
    assert len(evals) >= 7
    for path in experiences:
        store.validate("design/schemas/experience.schema.json", yaml.safe_load(path.read_text(encoding="utf-8")))
    for path in candidates:
        wrapper = yaml.safe_load(path.read_text(encoding="utf-8"))
        store.validate("design/schemas/candidate.schema.json", wrapper)
        proposed = yaml.safe_load((path.parent / "proposed/asset.yaml").read_text(encoding="utf-8"))
        kind = proposed["id"].split(":", 1)[0]
        store.validate(f"design/schemas/{kind}.schema.json", proposed)
    for path in evals:
        store.validate("design/schemas/eval.schema.json", yaml.safe_load(path.read_text(encoding="utf-8")))


def test_supersede_candidate_must_explicitly_reference_target(tmp_path: Path):
    from evolution_harness.evals import record_eval_result
    from evolution_harness.learning import LearningError, capture_experience, create_candidate, promote_candidate, triage_experience

    root = _copy_repo(tmp_path)
    capture_experience(root, _experience())
    triage_experience(root, "experience:agent-design:EXP001", "CROSS_PROJECT_CANDIDATE")
    proposed = _proposed_skill(capability_id="skill:agent-design:architecture-review-v2")
    proposed["relationships"]["supersedes"] = []
    definition = _eval_definition(eval_id="eval:agent-design:architecture-review-v2", target="skill:agent-design:architecture-review-v2")
    _write_eval(root, definition)
    record_eval_result(root, {
        "schemaVersion": "eval-result/v1", "evalResultId": "eval-result:agent-design:SUPER1",
        "evalId": definition["evalId"], "capabilityId": proposed["id"], "capabilityVersion": proposed["version"],
        "projectionVersion": "agent-skill-projection/1", "runtime": "CHATGPT", "model": "gpt-test",
        "executedAt": "2026-08-11T00:10:00Z", "result": "PASS", "evidence": ["manual://pass"]
    })
    candidate = _candidate(operation="SUPERSEDE", target="skill:agent-design:architecture-review")
    candidate["evalRequirements"] = [definition["evalId"]]
    create_candidate(root, candidate, proposed, "# Replacement Architecture Review\n")
    with pytest.raises(LearningError) as exc:
        promote_candidate(root, "candidate:agent-design:CAND001", apply=True)
    assert exc.value.code == "SUPERSESSION_TARGET_REQUIRED"
