from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


EXTERNAL_CAPABILITY_ID = "workflow:web-high-fidelity:reference-driven-visual-fidelity"


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


def _external_pack_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    from evolution_harness.project import build_capability_lock

    root, project = _copy_repo(tmp_path)
    registry_path = root / "core/registries/capability-packs.yaml"
    registrations = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    source = tmp_path / "external-pack"
    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "--no-hardlinks",
            registrations[0]["source"]["repositoryPath"],
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    registrations[0]["source"]["repositoryPath"] = str(source)
    registry_path.write_text(
        yaml.safe_dump(registrations, sort_keys=False), encoding="utf-8"
    )
    schema_path = root / "core/schemas/capability-pack-registration.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["properties"]["source"]["properties"]["repositoryPath"]["const"] = str(
        source
    )
    schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    binding_path = project / ".agent-evolution/capabilities.yaml"
    binding = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
    binding["capabilities"].append(EXTERNAL_CAPABILITY_ID)
    binding_path.write_text(yaml.safe_dump(binding, sort_keys=False), encoding="utf-8")
    build_capability_lock(root, project, write=True)
    return root, project, source


def test_resolver_selects_locked_external_pack_from_verified_registration(tmp_path: Path):
    root, project, _ = _external_pack_project(tmp_path)

    resolved = _resolve(
        root,
        project,
        intent="visual-reference-review",
        topic="web-fidelity",
        requested_output="review findings",
        runtime="CODEX",
    )

    selected = next(
        item
        for item in resolved["selectedCapabilities"]
        if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK"
    )
    assert selected == {
        "id": EXTERNAL_CAPABILITY_ID,
        "kind": "WORKFLOW",
        "version": "2.0.0",
        "contentHash": "9f2ffe458a32b75562107f7991b6b9cacc7630d8ec3e952a7abb409b8b54b8e1",
        "sourceKind": "EXTERNAL_CAPABILITY_PACK",
        "sourceRegistrationId": "pack:web-high-fidelity",
        "selectedBecause": ["explicit-binding"],
    }


def test_resolver_rejects_mutable_external_pack_checkout_drift(tmp_path: Path):
    root, project, source = _external_pack_project(tmp_path)
    skill_path = source / "skills/web-high-fidelity/SKILL.md"
    skill_path.write_text("mutable drift\n", encoding="utf-8")

    with pytest.raises(ValueError, match="external capability pack lock registration drift"):
        _resolve(
            root,
            project,
            intent="visual-reference-review",
            topic="web-fidelity",
            requested_output="review findings",
            runtime="CODEX",
        )


def test_resolver_rejects_external_pack_hidden_index_flag_drift(tmp_path: Path):
    root, project, source = _external_pack_project(tmp_path)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "update-index",
            "--assume-unchanged",
            "skills/web-high-fidelity/SKILL.md",
        ],
        check=True,
        capture_output=True,
    )

    with pytest.raises(ValueError, match="external capability pack lock registration drift"):
        _resolve(
            root,
            project,
            intent="visual-reference-review",
            topic="web-fidelity",
            requested_output="review findings",
            runtime="CODEX",
        )


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
    from evolution_harness.project import build_capability_lock

    root, project = _copy_repo(tmp_path)
    binding_path = project / ".agent-evolution/capabilities.yaml"
    binding = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
    binding["disabledCapabilities"].append("skill:agent-design:architecture-review")
    binding_path.write_text(yaml.safe_dump(binding, sort_keys=False), encoding="utf-8")
    build_capability_lock(root, project, write=True)
    result = _resolve(root, project, explicit_stage="FOCUSED_DESIGN")
    ids = {item["id"] for item in result["selectedCapabilities"]}
    assert "skill:agent-design:architecture-review" not in ids
    excluded = {item["id"]: item["excludedBecause"] for item in result["explain"]["excluded"]}
    assert "disabled" in excluded["skill:agent-design:architecture-review"]


def test_locked_capability_content_or_validity_drift_fails_closed(tmp_path: Path):
    import pytest

    root, project = _copy_repo(tmp_path)
    path = root / "design/capabilities/skills/architecture-review/asset.yaml"
    asset = yaml.safe_load(path.read_text(encoding="utf-8"))
    asset["validity"] = "INVALID"
    path.write_text(yaml.safe_dump(asset, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="capability lock"):
        _resolve(root, project, explicit_stage="FOCUSED_DESIGN")


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
