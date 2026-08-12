from __future__ import annotations

import shutil
from pathlib import Path

import yaml


def _copy_repo(tmp_path: Path) -> tuple[Path, Path]:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    for name in ["core", "design", "runtime", "examples"]:
        src = source / name
        if src.exists():
            shutil.copytree(src, root / name)
    return root, root / "examples/project-fixture"


def _resolve(root: Path, project: Path, **kwargs):
    from evolution_harness.resolver import resolve_design_context
    values = {
        "intent": "architecture-review",
        "topic": "resolver-mvp",
        "requested_output": "review findings",
        "runtime": "CHATGPT",
    }
    values.update(kwargs)
    return resolve_design_context(root, project, **values)


def test_resolver_metadata_selection_expands_workflow_and_dependencies_with_explain(tmp_path: Path):
    root, project = _copy_repo(tmp_path)
    result = _resolve(root, project)
    selected = {item["id"]: item for item in result["selectedCapabilities"]}
    assert "skill:agent-design:architecture-review" in selected
    assert "skill:agent-design:design-closure-assessment" in selected  # workflow-required at BOUNDARY_CLOSURE
    assert "framework:agent-design:authority-analysis" in selected
    assert "principle:agent-design:project-truth-over-generic-guidance" in selected
    assert "intent-match" in selected["skill:agent-design:architecture-review"]["selectedBecause"]
    assert "workflow-required" in selected["skill:agent-design:design-closure-assessment"]["selectedBecause"]
    assert any(reason.startswith("dependency-of:") for reason in selected["framework:agent-design:authority-analysis"]["selectedBecause"])
    assert result["workflowStage"] == "BOUNDARY_CLOSURE"
    assert result["humanGates"] == ["closure authority required"]
    assert result["topicGuard"] == "OPEN_OR_IN_PROGRESS"


def test_closed_topic_does_not_reopen_or_select_exploration_skill(tmp_path: Path):
    root, project = _copy_repo(tmp_path)
    state_path = project / ".agent-evolution/design-state.yaml"
    before = state_path.read_bytes()
    result = _resolve(root, project, topic="authority-model", explicit_stage="EXPLORATION")
    assert result["topicGuard"] == "DO_NOT_REOPEN"
    assert result["selectedCapabilities"] == []
    assert any(item["topicId"] == "authority-model" for item in result["closedTopics"])
    assert state_path.read_bytes() == before


def test_explicit_reopen_signal_is_represented_but_does_not_mutate_topic_state(tmp_path: Path):
    root, project = _copy_repo(tmp_path)
    state_path = project / ".agent-evolution/design-state.yaml"
    before = state_path.read_bytes()
    result = _resolve(root, project, topic="authority-model", explicit_stage="CALIBRATION", reopen_signal="NEW_EVIDENCE")
    assert result["topicGuard"] == "REOPEN_REVIEW_REQUIRED"
    assert result["reopenSignal"] == "NEW_EVIDENCE"
    assert result["selectedCapabilities"]
    assert state_path.read_bytes() == before


def test_disabled_capability_and_its_selection_are_removed_with_trace(tmp_path: Path):
    root, project = _copy_repo(tmp_path)
    binding_path = project / ".agent-evolution/capabilities.yaml"
    binding = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
    binding["disabledCapabilities"].append("skill:agent-design:architecture-review")
    binding_path.write_text(yaml.safe_dump(binding, sort_keys=False), encoding="utf-8")
    result = _resolve(root, project, explicit_stage="FOCUSED_DESIGN")
    ids = {item["id"] for item in result["selectedCapabilities"]}
    assert "skill:agent-design:architecture-review" not in ids
    excluded = {item["id"]: item["excludedBecause"] for item in result["explain"]["excluded"]}
    assert "disabled" in excluded["skill:agent-design:architecture-review"]


def test_invalid_current_capability_is_not_selected_and_explained(tmp_path: Path):
    root, project = _copy_repo(tmp_path)
    path = root / "design/capabilities/skills/architecture-review/asset.yaml"
    asset = yaml.safe_load(path.read_text(encoding="utf-8"))
    asset["validity"] = "INVALID"
    path.write_text(yaml.safe_dump(asset, sort_keys=False), encoding="utf-8")
    result = _resolve(root, project, explicit_stage="FOCUSED_DESIGN")
    assert "skill:agent-design:architecture-review" not in {item["id"] for item in result["selectedCapabilities"]}
    excluded = {item["id"]: item["excludedBecause"] for item in result["explain"]["excluded"]}
    assert "invalid" in excluded["skill:agent-design:architecture-review"]


def test_project_constraint_generates_project_truth_wins_conflict_signal(tmp_path: Path):
    root, project = _copy_repo(tmp_path)
    state_path = project / ".agent-evolution/design-state.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["projectConstraints"].append({
        "reference": "decision://project-fixture/local-architecture-rule",
        "conflictType": "EXPLICIT_PROJECT_CONSTRAINT",
        "conflictsWithCapabilities": ["skill:agent-design:architecture-review"],
    })
    state_path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")
    result = _resolve(root, project)
    signal = next(c for c in result["conflictSignals"] if c["sharedCapability"] == "skill:agent-design:architecture-review")
    assert signal["projectReference"] == "decision://project-fixture/local-architecture-rule"
    assert signal["resolutionRule"] == "PROJECT_TRUTH_WINS"
    assert signal["reviewRecommended"] is True


def test_project_stage_is_used_when_no_explicit_stage_and_nonmatching_skills_are_excluded(tmp_path: Path):
    root, project = _copy_repo(tmp_path)
    result = _resolve(root, project)
    assert result["stage"] == "BOUNDARY_CLOSURE"
    excluded = {item["id"]: item["excludedBecause"] for item in result["explain"]["excluded"]}
    assert "intent-mismatch" in excluded["skill:agent-design:baseline-finalization"] or "stage-mismatch" in excluded["skill:agent-design:baseline-finalization"]
