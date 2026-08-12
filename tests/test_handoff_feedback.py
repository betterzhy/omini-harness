from __future__ import annotations

import shutil
from pathlib import Path

import yaml


def _copy_repo(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    for name in ["core", "design"]:
        shutil.copytree(source / name, root / name)
    return root


def test_repository_feedback_enters_learning_as_untriaged_experience(tmp_path: Path):
    from evolution_harness.feedback import capture_feedback_as_experience

    root = _copy_repo(tmp_path)
    feedback = {
        "schemaVersion": "repository-feedback/v1",
        "feedbackId": "feedback:project-fixture:F001",
        "source": {"sourceType": "PROJECT_ARTIFACT", "reference": "repo://fixture/implementation", "visibility": "PROJECT"},
        "type": "UNVERIFIABLE_INVARIANT",
        "observedIssue": "An invariant cannot be verified from repository artifacts.",
        "impact": "Implementation confidence is reduced.",
        "affectedReferences": ["baseline://fixture/design/1.0"],
        "evidence": ["test://fixture/failure"],
        "suggestedDesignReview": "Review whether the design invariant is observable.",
        "capturedAt": "2026-08-11T00:20:00Z",
    }
    path = capture_feedback_as_experience(root, feedback, experience_id="experience:agent-design:FEEDBACK001")
    experience = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert experience["triageStatus"] == "UNTRIAGED"
    assert experience["source"]["reference"] == "feedback:project-fixture:F001"
    assert experience["signal"].startswith("UNVERIFIABLE_INVARIANT")
    assert "reopen" not in experience
