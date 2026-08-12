from __future__ import annotations

from pathlib import Path
from typing import Any

from .learning import capture_experience
from .schema import SchemaStore


def capture_feedback_as_experience(
    repository_root: Path,
    feedback: dict[str, Any],
    *,
    experience_id: str,
) -> Path:
    root = Path(repository_root)
    SchemaStore(root).validate("design/schemas/repository-feedback.schema.json", feedback)
    source_visibility = feedback["source"]["visibility"]
    experience = {
        "schemaVersion": "experience/v1",
        "experienceId": experience_id,
        "source": {
            "sourceType": "PROJECT_ARTIFACT",
            "reference": feedback["feedbackId"],
            "visibility": source_visibility,
            "distillation": feedback["observedIssue"][:1000],
        },
        "capturedAt": feedback["capturedAt"],
        "designStage": "ENGINEERING_DESIGN",
        "signal": f"{feedback['type']}: {feedback['observedIssue']}",
        "observedBehavior": feedback["observedIssue"],
        "humanCorrection": feedback["suggestedDesignReview"],
        "impact": feedback["impact"],
        "triageStatus": "UNTRIAGED",
        "candidateHints": list(feedback.get("affectedReferences", [])),
        "visibility": source_visibility,
    }
    return capture_experience(root, experience)
