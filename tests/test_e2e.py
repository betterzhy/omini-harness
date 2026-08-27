from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from capability_pack_test_support import retain_web_registration_fixture


def _copy_repo(tmp_path: Path) -> tuple[Path, Path]:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    for name in ["core", "design", "engineering", "runtime", "examples", "contracts", "policies", "skills", "verification"]:
        src = source / name
        if src.exists():
            shutil.copytree(src, root / name)
    retain_web_registration_fixture(root)
    return root, root / "examples/project-fixture"


def _authorize_candidate(root: Path, seed: str) -> str:
    path = root / "design/learning/candidates" / seed / "candidate.yaml"
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    value["promotionStatus"] = "AUTHORIZED"
    value["authorityDecision"] = "APPROVE"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return value["candidateId"]


def _record(root: Path, *, result_id: str, eval_id: str, capability_id: str, version: str) -> None:
    from evolution_harness.evals import record_eval_result

    record_eval_result(root, {
        "schemaVersion": "eval-result/v1",
        "evalResultId": result_id,
        "evalId": eval_id,
        "capabilityId": capability_id,
        "capabilityVersion": version,
        "projectionVersion": "agent-skill-projection/1",
        "runtime": "CHATGPT",
        "model": "gpt-e2e-fixture",
        "executedAt": "2026-08-11T01:00:00Z",
        "result": "PASS",
        "evidence": ["manual://e2e-pass"],
    })


def test_experience_candidate_eval_promotion_resolution_projection_flow(tmp_path: Path):
    from evolution_harness.catalog import build_all_catalogs
    from evolution_harness.learning import promote_candidate
    from evolution_harness.project import build_capability_lock
    from evolution_harness.projection import build_projection_pack
    from evolution_harness.registry import build_all_registries
    from evolution_harness.resolver import resolve_design_context

    root, project = _copy_repo(tmp_path)
    candidate_id = _authorize_candidate(root, "candidate__agent-design__CAND-SEED-001")
    _record(
        root,
        result_id="eval-result:agent-design:E2E-PROMOTION",
        eval_id="eval:agent-design:authority-gap-review",
        capability_id="skill:agent-design:authority-gap-review",
        version="1.0.0",
    )
    promoted = promote_candidate(root, candidate_id, apply=True)
    assert promoted["applied"] is True

    build_all_registries(root, write=True)
    build_all_catalogs(root, write=True)
    binding_path = project / ".agent-evolution/capabilities.yaml"
    binding = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
    binding["extensions"].append("skill:agent-design:authority-gap-review")
    binding_path.write_text(yaml.safe_dump(binding, sort_keys=False), encoding="utf-8")
    lock = build_capability_lock(root, project, write=True)
    assert any(item["capabilityId"] == "skill:agent-design:authority-gap-review" for item in lock["capabilities"])

    resolved = resolve_design_context(
        root, project, intent="architecture-review", topic="resolver-mvp", requested_output="review findings", runtime="CHATGPT"
    )
    assert any(item["id"] == "skill:agent-design:authority-gap-review" for item in resolved["selectedCapabilities"])
    build_projection_pack(root, project, resolved, runtime="CHATGPT")
    assert (root / "generated/projections/chatgpt/project-fixture/skills/authority-gap-review/SKILL.md").exists()


def test_scope_broadening_requires_transfer_gate_and_invalidates_old_exact_lock(tmp_path: Path):
    from evolution_harness.catalog import build_design_active_catalog
    from evolution_harness.learning import promote_candidate
    from evolution_harness.project import build_capability_lock
    from evolution_harness.registry import build_design_registry

    root, project = _copy_repo(tmp_path)
    old_lock = build_capability_lock(root, project, write=True)
    old_arch = next(item for item in old_lock["capabilities"] if item["capabilityId"] == "skill:agent-design:architecture-review")
    assert old_arch["resolvedVersion"] == "1.0.0"

    candidate_id = _authorize_candidate(root, "candidate__agent-design__CAND-SEED-002")
    _record(
        root,
        result_id="eval-result:agent-design:E2E-TRANSFER",
        eval_id="eval:agent-design:architecture-review-transfer",
        capability_id="skill:agent-design:architecture-review",
        version="1.1.0",
    )
    promote_candidate(root, candidate_id, apply=True)
    catalog = build_design_active_catalog(root, write=False)
    current = next(item for item in catalog["entries"] if item["id"] == "skill:agent-design:architecture-review")
    assert current["version"] == "1.1.0"
    registry = build_design_registry(root, write=False)
    history = [item for item in registry["entries"] if item["id"] == "skill:agent-design:architecture-review"]
    assert [(item["version"], item["isCurrent"]) for item in history] == [("1.0.0", False), ("1.1.0", True)]

    stored_old = yaml.safe_load((project / ".agent-evolution/capabilities.lock.yaml").read_text(encoding="utf-8"))
    expected_new = build_capability_lock(root, project, write=False)
    assert stored_old != expected_new
    new_lock = build_capability_lock(root, project, write=True)
    new_arch = next(item for item in new_lock["capabilities"] if item["capabilityId"] == "skill:agent-design:architecture-review")
    assert new_arch["resolvedVersion"] == "1.1.0"


def test_supersession_preserves_history_but_removes_old_identity_from_active_catalog(tmp_path: Path):
    from evolution_harness.catalog import build_design_active_catalog
    from evolution_harness.evals import record_eval_result
    from evolution_harness.learning import capture_experience, create_candidate, promote_candidate, triage_experience
    from evolution_harness.registry import build_design_registry

    root, _ = _copy_repo(tmp_path)
    experience = {
        "schemaVersion": "experience/v1",
        "experienceId": "experience:agent-design:E2E-SUPERSEDE",
        "source": {"sourceType": "HUMAN_REVIEW", "reference": "review://e2e/supersession", "visibility": "SHARED"},
        "capturedAt": "2026-08-11T01:10:00Z",
        "designStage": "CALIBRATION",
        "signal": "The replacement review skill has a materially different semantic contract.",
        "observedBehavior": "Keeping the old identity would hide a breaking semantic change.",
        "humanCorrection": "Use a new identity and explicit supersession relation.",
        "impact": "Historical discovery is retained while new runtime selection uses the replacement.",
        "triageStatus": "UNTRIAGED",
        "candidateHints": ["skill:agent-design:architecture-review-v2"],
        "visibility": "SHARED",
    }
    capture_experience(root, experience)
    triage_experience(root, experience["experienceId"], "CROSS_PROJECT_CANDIDATE")

    source_asset = yaml.safe_load((root / "design/capabilities/skills/architecture-review/asset.yaml").read_text(encoding="utf-8"))
    proposed = dict(source_asset)
    proposed["id"] = "skill:agent-design:architecture-review-v2"
    proposed["version"] = "1.0.0"
    proposed["title"] = "Architecture Review V2"
    proposed["summary"] = "Replacement architecture review semantic contract."
    proposed["relationships"] = {**source_asset["relationships"], "supersedes": ["skill:agent-design:architecture-review"]}
    proposed["evalBindings"] = ["eval:agent-design:architecture-review-v2"]
    proposed["provenance"] = [{"sourceType": "HUMAN_REVIEW", "reference": "candidate://e2e/supersession", "visibility": "SHARED"}]
    eval_definition = {
        "schemaVersion": "design-eval/v1",
        "evalId": "eval:agent-design:architecture-review-v2",
        "targetCapability": proposed["id"],
        "scenario": "Replacement architecture review must preserve project authority.",
        "hiddenRisks": ["silent authority drift"],
        "expectedReasoningCoverage": ["authority resolution"],
        "expectedQuestions": ["What project fact is authoritative?"],
        "forbiddenAssumptions": ["Shared guidance is project truth."],
        "criticalBoundaries": ["Project truth wins."],
        "acceptableAlternativeOutcomes": ["Escalate to human authority."],
        "regressionCriteria": ["Old semantic contract is selected as current."],
        "transferScope": ["agent-design"],
        "modelSensitivity": "MODEL_INDEPENDENT",
    }
    eval_path = root / "design/evals/eval_agent-design_architecture-review-v2.yaml"
    eval_path.write_text(yaml.safe_dump(eval_definition, sort_keys=False), encoding="utf-8")
    record_eval_result(root, {
        "schemaVersion": "eval-result/v1", "evalResultId": "eval-result:agent-design:E2E-SUPERSEDE",
        "evalId": eval_definition["evalId"], "capabilityId": proposed["id"], "capabilityVersion": "1.0.0",
        "projectionVersion": "agent-skill-projection/1", "runtime": "CHATGPT", "model": "gpt-e2e-fixture",
        "executedAt": "2026-08-11T01:20:00Z", "result": "PASS", "evidence": ["manual://e2e-pass"],
    })
    candidate = {
        "schemaVersion": "candidate/v1", "candidateId": "candidate:agent-design:E2E-SUPERSEDE",
        "operation": "SUPERSEDE", "targetCapability": "skill:agent-design:architecture-review",
        "sourceExperiences": [experience["experienceId"]], "scopeHypothesis": "Same applicability with a breaking semantic contract.",
        "expectedImprovement": "Make breaking semantic change explicit.",
        "evidence": [{"sourceType": "HUMAN_REVIEW", "reference": "review://e2e/supersession", "visibility": "SHARED"}],
        "counterexamples": [], "evalRequirements": [eval_definition["evalId"]],
        "promotionStatus": "AUTHORIZED", "authorityDecision": "APPROVE",
    }
    create_candidate(root, candidate, proposed, "# Architecture Review V2\n\nUse explicit replacement semantics.\n")
    promote_candidate(root, candidate["candidateId"], apply=True)

    registry = build_design_registry(root, write=False)
    assert any(item["id"] == "skill:agent-design:architecture-review" for item in registry["entries"])
    catalog_ids = {item["id"] for item in build_design_active_catalog(root, write=False)["entries"]}
    assert "skill:agent-design:architecture-review-v2" in catalog_ids
    assert "skill:agent-design:architecture-review" not in catalog_ids
