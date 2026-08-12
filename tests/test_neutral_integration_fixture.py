from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_neutral_fixture_scenarios_cover_authority_closure_consumed_and_conflict(tmp_path: Path):
    from evolution_harness.authority import build_authority_snapshot
    from evolution_harness.scenario import run_integration_scenario

    root = Path(__file__).parents[1]
    integration = root / "integrations/neutral-shadow"
    source = tmp_path / "external-project"
    shutil.copytree(root / "examples/external-project-source", source)
    before = _tree_bytes(source)

    results = [
        run_integration_scenario(root, integration, source, scenario)
        for scenario in sorted((integration / "scenarios").glob("*.yaml"))
    ]
    assert results and all(result["gate"] == "PASS" for result in results)
    snapshot = build_authority_snapshot(root, integration, source)
    assert any(item["role"] == "SPECIALIZED" for item in snapshot["authorities"])
    assert any(item["role"] == "DERIVED" for item in snapshot["authorities"])
    assert snapshot["facts"]["permission.stage4"]["normalizedValue"] == "CONSUMED"
    assert before == _tree_bytes(source)


def test_neutral_fixture_excluded_authority_fails_before_consumption(tmp_path: Path):
    from evolution_harness.authority import IntegrationAuthorityError, build_authority_snapshot

    source_root = Path(__file__).parents[1]
    root = tmp_path / "harness"
    for name in ["core", "design", "runtime"]:
        shutil.copytree(source_root / name, root / name)
    integration = root / "integrations/neutral-shadow"
    shutil.copytree(source_root / "integrations/neutral-shadow", integration)
    source = tmp_path / "external-project"
    shutil.copytree(source_root / "examples/external-project-source", source)
    authority_path = integration / "authority-map.yaml"
    authority_map = yaml.safe_load(authority_path.read_text(encoding="utf-8"))
    authority_map["authorities"].append(
        {
            "id": "poisoned-secret",
            "path": "private/secret.md",
            "format": "MARKDOWN_KV",
            "role": "CANONICAL",
            "required": True,
            "owns": ["secret.value"],
            "selectors": {"secret.value": {"key": "Secret", "required": True}},
        }
    )
    authority_path.write_text(yaml.safe_dump(authority_map, sort_keys=False), encoding="utf-8")

    with pytest.raises(IntegrationAuthorityError, match="authority path is excluded"):
        build_authority_snapshot(root, integration, source)


def test_neutral_fixture_canonical_topic_reopen_cannot_be_hidden_by_closed_sidecar(tmp_path: Path):
    from evolution_harness.integration import resolve_integration_context

    root = Path(__file__).parents[1]
    integration = root / "integrations/neutral-shadow"
    source = tmp_path / "external-project"
    shutil.copytree(root / "examples/external-project-source", source)
    decisions = source / "decisions.md"
    decisions.write_text(
        decisions.read_text(encoding="utf-8").replace("ApiBoundaryStatus = CLOSED", "ApiBoundaryStatus = OPEN"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="topic status authority mismatch"):
        resolve_integration_context(
            root,
            integration,
            source,
            intent="architecture-review",
            topic="api-boundary",
            requested_output="review findings",
            runtime="CODEX",
        )


def test_neutral_fixture_projection_install_round_trip_is_target_scoped(tmp_path: Path):
    from evolution_harness.install import ProjectionInstallError, install_projection, uninstall_projection
    from evolution_harness.integration import build_integration_projection

    repository = Path(__file__).parents[1]
    root = tmp_path / "harness"
    for name in ["core", "design", "runtime"]:
        shutil.copytree(repository / name, root / name)
    integration = root / "integrations/neutral-shadow"
    shutil.copytree(repository / "integrations/neutral-shadow", integration)
    source = tmp_path / "external-project"
    shutil.copytree(repository / "examples/external-project-source", source)
    source_before = _tree_bytes(source)

    build_integration_projection(
        root,
        integration,
        source,
        intent="architecture-review",
        topic="runtime-integration",
        requested_output="review findings",
        runtime="CODEX",
    )
    pack = root / "generated/projections/codex/neutral-shadow"
    # The installation target must itself be the registered integration source;
    # use a second source copy to prove the source/target boundary without touching the fixture authority tree.
    target = tmp_path / "install-target-source"
    shutil.copytree(source, target)
    (target / "AGENTS.md").write_text("# Project owned\n", encoding="utf-8")
    assert install_projection(root, pack, target)["mode"] == "DRY_RUN"
    with pytest.raises(ProjectionInstallError, match="automatic projection install is disabled"):
        install_projection(root, pack, target, apply=True)
    assert not (target / ".agents/skills/architecture-review/SKILL.md").exists()
    with pytest.raises(ProjectionInstallError, match="automatic projection uninstall is disabled"):
        uninstall_projection(root, target, apply=True)
    assert not (target / ".agents/skills/architecture-review/SKILL.md").exists()
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "# Project owned\n"
    assert source_before == _tree_bytes(source)


def test_core_runtime_contains_no_project_specific_pay_nexus_branching():
    root = Path(__file__).parents[1]
    checked = [*sorted((root / "src/evolution_harness").glob("*.py")), *sorted((root / "core/schemas").glob("*.json"))]
    hits = [path for path in checked if "pay-nexus" in path.read_text(encoding="utf-8").lower()]
    assert hits == []
