from __future__ import annotations

import shutil
from pathlib import Path

import yaml


def _copy_repo(tmp_path: Path) -> tuple[Path, Path]:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    for name in ["core", "design", "runtime", "examples"]:
        shutil.copytree(source / name, root / name)
    return root, root / "examples/project-fixture"


def test_design_handoff_is_reference_first_and_generated(tmp_path: Path):
    from evolution_harness.handoff import build_design_handoff

    root, project = _copy_repo(tmp_path)
    input_path = project / ".agent-evolution/handoff-input.yaml"
    input_path.write_text(
        yaml.safe_dump(
            {
                "schemaVersion": "design-handoff-input/v1",
                "entityReferences": ["entity://project-fixture/resolver"],
                "invariantReferences": ["invariant://project-fixture/project-truth-wins"],
                "protectedBoundaryReferences": ["boundary://project-fixture/authority"],
                "externalContractReferences": ["contract://project-fixture/runtime-pack"],
                "implementationConstraints": ["Use deterministic metadata resolution before semantic fallback."],
                "openEngineeringQuestions": ["How should the projection pack be installed?"],
                "verificationObligations": ["Verify exact capability lock and projection freshness."],
                "reopenConditions": ["IMPLEMENTATION_FEEDBACK"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    handoff = build_design_handoff(root, project, write=True)
    assert handoff["baselineReferences"] == ["baseline://project-fixture/authority-model/1.0"]
    assert "decision://project-fixture/project-truth-wins" in handoff["decisionReferences"]
    assert handoff["entityReferences"] == ["entity://project-fixture/resolver"]
    assert handoff["fieldAuthority"]["baselineReferences"] == "PROJECT_CANONICAL_REFERENCE"
    assert handoff["fieldAuthority"]["implementationConstraints"] == "PROJECT_HANDOFF_INPUT"
    assert "authority-model" not in str(handoff.get("baselineBody", ""))
    stored = yaml.safe_load((project / ".agent-evolution/design-handoff.yaml").read_text(encoding="utf-8"))
    assert stored == handoff


def test_design_handoff_source_revision_changes_when_authoritative_state_changes(tmp_path: Path):
    from evolution_harness.handoff import build_design_handoff

    root, project = _copy_repo(tmp_path)
    source = Path(__file__).parents[1] / "examples/project-fixture/.agent-evolution/handoff-input.yaml"
    shutil.copy2(source, project / ".agent-evolution/handoff-input.yaml")
    first = build_design_handoff(root, project)
    state_path = project / ".agent-evolution/design-state.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["assumptions"].append("assumption://project-fixture/new-evidence")
    state_path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")
    second = build_design_handoff(root, project)
    assert first["sourceRevision"] != second["sourceRevision"]
