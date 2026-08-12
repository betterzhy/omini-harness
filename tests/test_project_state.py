from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml


def _copy_repo(tmp_path: Path) -> tuple[Path, Path]:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    for name in ["core", "design", "runtime", "examples"]:
        src = source / name
        if src.exists():
            shutil.copytree(src, root / name)
    return root, root / "examples/project-fixture"


def test_project_fixture_state_and_binding_validate():
    from evolution_harness.schema import SchemaStore

    root = Path(__file__).parents[1]
    store = SchemaStore(root)
    project = root / "examples/project-fixture/.agent-evolution"
    state = yaml.safe_load((project / "design-state.yaml").read_text(encoding="utf-8"))
    binding = yaml.safe_load((project / "capabilities.yaml").read_text(encoding="utf-8"))
    store.validate("core/schemas/project-design-state.schema.json", state)
    store.validate("core/schemas/project-capability-binding.schema.json", binding)
    closed = next(t for t in state["topics"] if t["status"] == "CLOSED")
    assert {"closedAt", "closedBy", "baselineReference", "reopenConditions"} <= set(closed)


def test_closed_topic_schema_requires_authority_and_reopen_metadata():
    from evolution_harness.schema import SchemaStore, SchemaValidationError

    root = Path(__file__).parents[1]
    value = {
        "schemaVersion": "project-design-state/v1",
        "project": "x",
        "currentStage": "CALIBRATION",
        "topics": [{"topicId": "closed", "status": "CLOSED", "scope": {}}],
        "baselines": [], "assumptions": [], "openDecisions": [], "nextTopicCandidates": [],
        "projectAuthorityReferences": [], "protectedDecisions": [], "projectConstraints": []
    }
    with pytest.raises(SchemaValidationError):
        SchemaStore(root).validate("core/schemas/project-design-state.schema.json", value)


def test_capability_lock_is_exact_and_traceable(tmp_path: Path):
    from evolution_harness.project import build_capability_lock

    root, project = _copy_repo(tmp_path)
    lock = build_capability_lock(root, project, write=True)
    assert lock["schemaVersion"] == "capability-lock/v1"
    assert len(lock["capabilities"]) == 10
    assert all({"capabilityId", "resolvedVersion", "contentHash", "sourceHarnessRevision"} <= set(item) for item in lock["capabilities"])
    assert all(item["resolvedVersion"].count(".") == 2 for item in lock["capabilities"])
    stored = yaml.safe_load((project / ".agent-evolution/capabilities.lock.yaml").read_text(encoding="utf-8"))
    assert stored == lock
