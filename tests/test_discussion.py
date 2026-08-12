from __future__ import annotations

import shutil
from pathlib import Path


def _copy_repo(tmp_path: Path) -> tuple[Path, Path]:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    for name in ["core", "design", "runtime", "examples"]:
        src = source / name
        if src.exists():
            shutil.copytree(src, root / name)
    return root, root / "examples/project-fixture"


def _resolved(root: Path, project: Path):
    from evolution_harness.resolver import resolve_design_context
    return resolve_design_context(
        root, project, intent="architecture-review", topic="resolver-mvp",
        requested_output="review findings", runtime="CHATGPT"
    )


def test_discussion_contract_materializes_required_deterministic_sections(tmp_path: Path):
    from evolution_harness.discussion import materialize_discussion_contract

    root, project = _copy_repo(tmp_path)
    resolved = _resolved(root, project)
    first = materialize_discussion_contract(root, project, resolved)
    second = materialize_discussion_contract(root, project, resolved)
    assert first == second
    for heading in [
        "# Discussion Contract", "## Topic", "## Background References", "## Known CLOSED Topics",
        "## Scope", "## Non-Goals", "## Core Questions", "## Constraints", "## Expected Outputs",
        "## Closure Criteria", "## Next Stage"
    ]:
        assert heading in first
    assert "resolver-mvp" in first
    assert "baseline://project-fixture/authority-model/1.0" in first
    assert "PROJECT_TRUTH_WINS" in first


def test_discussion_contract_is_ephemeral_unless_explicitly_persisted(tmp_path: Path):
    from evolution_harness.discussion import materialize_discussion_contract

    root, project = _copy_repo(tmp_path)
    resolved = _resolved(root, project)
    generated = root / "generated/resolutions"
    materialize_discussion_contract(root, project, resolved)
    assert not generated.exists()
    target = generated / "contract.md"
    materialize_discussion_contract(root, project, resolved, persist_path=target)
    assert target.exists()


def test_workflow_transition_metadata_allows_bounded_optional_stage_skips(tmp_path: Path):
    from evolution_harness.discussion import next_workflow_stages

    root, _ = _copy_repo(tmp_path)
    assert next_workflow_stages(root, "EXPLORATION") == ["FOCUSED_DESIGN", "CALIBRATION"]
    assert next_workflow_stages(root, "CALIBRATION") == ["BOUNDARY_CLOSURE", "BASELINE"]
    assert "REPOSITORY_LANDING" not in next_workflow_stages(root, "EXPLORATION")


def test_next_topic_routing_uses_project_state_and_never_returns_closed_topic(tmp_path: Path):
    from evolution_harness.discussion import route_next_topics

    root, project = _copy_repo(tmp_path)
    result = route_next_topics(root, project, current_topic="resolver-mvp")
    ids = [item["topicId"] for item in result["candidates"]]
    assert "authority-model" not in ids
    assert "runtime-projection" in ids
    candidate = next(item for item in result["candidates"] if item["topicId"] == "runtime-projection")
    assert candidate["rankingInputs"]["status"] == "OPEN"
    assert candidate["rankingInputs"]["dependenciesSatisfied"] is False  # resolver-mvp is still IN_PROGRESS
    assert result["usesSemanticPlanner"] is False


def test_next_topic_routing_changes_eligibility_when_dependency_closes_without_ai_planner(tmp_path: Path):
    import yaml
    from evolution_harness.discussion import route_next_topics

    root, project = _copy_repo(tmp_path)
    state_path = project / ".agent-evolution/design-state.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    resolver_topic = next(t for t in state["topics"] if t["topicId"] == "resolver-mvp")
    resolver_topic.update({
        "status": "CLOSED", "closedAt": "2026-08-11T02:00:00Z", "closedBy": "HUMAN_AUTHORITY",
        "baselineReference": "baseline://project-fixture/resolver-mvp/1.0", "reopenConditions": ["NEW_EVIDENCE", "EXPLICIT_AUTHORITY"]
    })
    state_path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")
    result = route_next_topics(root, project, current_topic="resolver-mvp")
    candidate = next(item for item in result["candidates"] if item["topicId"] == "runtime-projection")
    assert candidate["rankingInputs"]["dependenciesSatisfied"] is True
    assert candidate["eligible"] is True
