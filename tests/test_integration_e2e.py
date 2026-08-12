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


def test_integration_intent_alias_selects_locked_capability_and_preserves_request_intent(
    tmp_path: Path,
):
    from evolution_harness.integration import resolve_integration_context
    from evolution_harness.project import verify_capability_lock

    root, integration, source = _fixture(tmp_path)
    state_path = integration / "control-plane/.agent-evolution/design-state.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["intentAliases"] = {
        "implementation-readiness-review": "architecture-review",
    }
    state_path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")
    lock_before, _ = verify_capability_lock(root, integration / "control-plane")

    resolved = resolve_integration_context(
        root,
        integration,
        source,
        intent="implementation-readiness-review",
        topic="next-development-slice-admission",
        requested_output="next Slice admission guidance and exact planning constraints",
        runtime="CODEX",
    )

    selected = {item["id"]: item for item in resolved["selectedCapabilities"]}
    lock_after, _ = verify_capability_lock(root, integration / "control-plane")
    assert resolved["intent"] == "implementation-readiness-review"
    assert resolved["selectionIntent"] == "architecture-review"
    assert "skill:agent-design:architecture-review" in selected
    assert (
        "intent-alias:implementation-readiness-review->architecture-review"
        in selected["skill:agent-design:architecture-review"]["selectedBecause"]
    )
    assert lock_after["lockFingerprint"] == lock_before["lockFingerprint"]


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
    assert freshness.reasons == ("projection-integrity-drift",)


def test_integration_projection_rejects_forged_authority_facts_with_unchanged_identity(tmp_path: Path):
    from evolution_harness.authority import build_authority_snapshot
    from evolution_harness.integration import check_integration_projection
    from evolution_harness.projection import ProjectionError, build_projection_pack

    root, integration, source = _fixture(tmp_path)
    resolved = _resolve(root, integration, source)
    snapshot = build_authority_snapshot(root, integration, source)
    resolved["authorityFacts"]["permission.execute"]["normalizedValue"] = "ALLOW"
    control = integration / "control-plane"

    with pytest.raises(ProjectionError, match="live snapshot"):
        build_projection_pack(
            root,
            control,
            resolved,
            runtime="CODEX",
            authority_snapshot=snapshot,
        )

    assert not (root / "generated/projections/codex/sample-shadow").exists()
    assert not check_integration_projection(root, integration, source, runtime="CODEX").fresh


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


def test_integration_install_cli_separates_live_authority_source_from_disposable_target(
    tmp_path: Path,
):
    from evolution_harness.integration import build_integration_projection

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
    target = tmp_path / "disposable-target"
    target.mkdir()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "evolution_harness.cli",
            "--repository-root",
            str(root),
            "projection",
            "install",
            "--pack",
            str(root / "generated/projections/codex/sample-shadow"),
            "--source",
            str(source),
            "--target",
            str(target),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["data"]["mode"] == "DRY_RUN"
    assert payload["data"]["gate"] == "PASS"
    assert {
        (item["operation"], item["source"], item["target"])
        for item in payload["data"]["actions"]
    } == {
        (
            "CREATE",
            "skills/architecture-review/SKILL.md",
            ".agents/skills/architecture-review/SKILL.md",
        ),
        (
            "CREATE",
            "skills/design-closure-assessment/SKILL.md",
            ".agents/skills/design-closure-assessment/SKILL.md",
        ),
    }
    assert list(target.iterdir()) == []
