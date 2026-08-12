from __future__ import annotations

import shutil
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def _write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repository = Path(__file__).parents[1]
    root = tmp_path / "harness"
    for name in ["core", "design", "runtime", "examples"]:
        shutil.copytree(repository / name, root / name)
    integration = root / "integrations/sample-shadow"
    control = integration / "control-plane"
    shutil.copytree(root / "examples/project-fixture/.agent-evolution", control / ".agent-evolution")
    state_path = control / ".agent-evolution/design-state.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["project"] = "sample-shadow"
    state_path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")

    source = tmp_path / "source-project"
    source.mkdir()
    (source / "status.md").write_text(
        "CurrentStage = READY\nExecutionAllowed = NO_WINDOW_CLOSED\n", encoding="utf-8"
    )
    _write_yaml(
        integration / "integration.yaml",
        {
            "schemaVersion": "project-integration/v1",
            "id": "sample-shadow",
            "projectId": "sample-shadow",
            "sourceAccess": "READ_ONLY",
            "controlPlanePath": "control-plane",
            "authorityMapPath": "authority-map.yaml",
            "runtime": "CODEX",
            "excludedPaths": ["private/**"],
        },
    )
    _write_yaml(
        integration / "authority-map.yaml",
        {
            "schemaVersion": "project-authority-map/v1",
            "authorities": [
                {
                    "id": "global-status",
                    "path": "status.md",
                    "format": "MARKDOWN_KV",
                    "role": "CANONICAL",
                    "required": True,
                    "owns": ["project.stage", "permission.execute"],
                    "selectors": {
                        "project.stage": {"key": "CurrentStage", "required": True},
                        "permission.execute": {
                            "key": "ExecutionAllowed",
                            "required": True,
                            "normalization": {
                                "rules": [
                                    {"operator": "PREFIX", "expected": "YES", "value": "ALLOW"},
                                    {"operator": "PREFIX", "expected": "NO", "value": "DENY"},
                                ],
                                "default": "UNKNOWN",
                            },
                        },
                    },
                }
            ],
            "requiredFacts": ["project.stage", "permission.execute"],
        },
    )
    from evolution_harness.project import build_capability_lock

    build_capability_lock(root, control, write=True)
    return root, integration, source


def _resolve(root: Path, integration: Path, source: Path):
    from evolution_harness.integration import resolve_integration_context

    return resolve_integration_context(
        root,
        integration,
        source,
        intent="architecture-review",
        topic="resolver-mvp",
        requested_output="review findings",
        runtime="CODEX",
    )


def test_integration_resolution_binds_authority_snapshot(tmp_path: Path):
    root, integration, source = _fixture(tmp_path)
    resolved = _resolve(root, integration, source)
    assert resolved["authoritySnapshotFingerprint"].startswith("sha256:")
    assert resolved["authorityGate"] == "PASS"
    assert resolved["authorityFacts"]["permission.execute"]["normalizedValue"] == "DENY"
    assert resolved["project"] == "sample-shadow"


def test_integration_projection_freshness_detects_authority_drift(tmp_path: Path):
    from evolution_harness.integration import build_integration_projection, check_integration_projection

    root, integration, source = _fixture(tmp_path)
    manifest = build_integration_projection(
        root,
        integration,
        source,
        intent="architecture-review",
        topic="resolver-mvp",
        requested_output="review findings",
        runtime="CODEX",
    )
    assert manifest["authoritySnapshotFingerprint"].startswith("sha256:")
    assert check_integration_projection(root, integration, source, runtime="CODEX").fresh

    (source / "status.md").write_text(
        "CurrentStage = READY\nExecutionAllowed = YES_EXPLICIT\n", encoding="utf-8"
    )
    freshness = check_integration_projection(root, integration, source, runtime="CODEX")
    assert not freshness.fresh
    assert "authority-snapshot-drift" in freshness.reasons


def test_integration_projection_check_binds_requested_context(tmp_path: Path):
    from evolution_harness.integration import build_integration_projection, check_integration_projection

    root, integration, source = _fixture(tmp_path)
    build_integration_projection(
        root,
        integration,
        source,
        intent="architecture-review",
        topic="resolver-mvp",
        requested_output="review findings",
        runtime="CODEX",
    )
    freshness = check_integration_projection(
        root,
        integration,
        source,
        intent="architecture-review",
        topic="resolver-mvp",
        requested_output="different output contract",
        runtime="CODEX",
    )
    assert not freshness.fresh
    assert "resolution-context-drift" in freshness.reasons


def test_integration_resolution_stops_on_authority_no_go(tmp_path: Path):
    root, integration, source = _fixture(tmp_path)
    (source / "status.md").write_text("CurrentStage = READY\n", encoding="utf-8")
    with pytest.raises(ValueError, match="authority snapshot gate is NO_GO"):
        _resolve(root, integration, source)


def test_integration_resolution_rejects_sidecar_topic_status_authority_drift(tmp_path: Path):
    root, integration, source = _fixture(tmp_path)
    config_path = integration / "integration.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["topicStatusFacts"] = {"authority-model": "project.stage"}
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="topic status authority mismatch"):
        _resolve(root, integration, source)


def test_integration_cli_resolves_and_builds_projection_from_generic_paths(tmp_path: Path):
    root, integration, source = _fixture(tmp_path)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    common = [
        sys.executable,
        "-m",
        "evolution_harness.cli",
        "--repository-root",
        str(root),
        "integration",
    ]
    resolution = subprocess.run(
        [
            *common,
            "resolve",
            "--integration",
            str(integration),
            "--source",
            str(source),
            "--intent",
            "architecture-review",
            "--topic",
            "resolver-mvp",
            "--output",
            "review findings",
            "--runtime",
            "CODEX",
            "--explain",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    payload = json.loads(resolution.stdout)
    assert payload["ok"]
    assert payload["data"]["authorityGate"] == "PASS"

    projection = subprocess.run(
        [
            *common,
            "projection",
            "--integration",
            str(integration),
            "--source",
            str(source),
            "--intent",
            "architecture-review",
            "--topic",
            "resolver-mvp",
            "--output",
            "review findings",
            "--runtime",
            "CODEX",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert json.loads(projection.stdout)["data"]["authoritySnapshotFingerprint"].startswith("sha256:")
