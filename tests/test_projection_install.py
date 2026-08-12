from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest


def _pack(tmp_path: Path) -> tuple[Path, Path, Path]:
    from evolution_harness.projection import build_projection_pack
    from evolution_harness.resolver import resolve_design_context

    source = Path(__file__).parents[1]
    root = tmp_path / "harness"
    for name in ["core", "design", "runtime", "examples"]:
        shutil.copytree(source / name, root / name)
    project = root / "examples/project-fixture"
    resolved = resolve_design_context(
        root,
        project,
        intent="architecture-review",
        topic="resolver-mvp",
        requested_output="review findings",
        runtime="CODEX",
    )
    build_projection_pack(root, project, resolved, runtime="CODEX")
    return root, project, root / "generated/projections/codex/project-fixture"


def test_install_is_dry_run_by_default_and_never_touches_agents_md(tmp_path: Path):
    from evolution_harness.install import install_projection

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    agents = target / "AGENTS.md"
    agents.write_text("# Project-owned guidance\n", encoding="utf-8")

    plan = install_projection(root, pack, target)

    assert plan["mode"] == "DRY_RUN"
    assert plan["gate"] == "PASS"
    assert plan["actions"]
    assert not (target / ".agents").exists()
    assert agents.read_text(encoding="utf-8") == "# Project-owned guidance\n"


def test_install_apply_writes_only_manifested_skills_and_uninstall_is_managed(tmp_path: Path):
    from evolution_harness.install import install_projection, uninstall_projection

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    agents = target / "AGENTS.md"
    agents.write_text("# Keep me\n", encoding="utf-8")

    result = install_projection(root, pack, target, apply=True)
    assert result["mode"] == "APPLY"
    managed = target / ".agent-evolution/projection-install-manifest.json"
    manifest = json.loads(managed.read_text(encoding="utf-8"))
    installed = [target / item["path"] for item in manifest["installedFiles"]]
    assert installed and all(path.exists() for path in installed)
    assert all(path.as_posix().endswith("/SKILL.md") for path in installed)
    assert agents.read_text(encoding="utf-8") == "# Keep me\n"

    plan = uninstall_projection(root, target)
    assert plan["mode"] == "DRY_RUN" and all(path.exists() for path in installed)
    uninstall_projection(root, target, apply=True)
    assert not managed.exists()
    assert all(not path.exists() for path in installed)
    assert agents.read_text(encoding="utf-8") == "# Keep me\n"


def test_install_rejects_project_owned_skill_collision(tmp_path: Path):
    from evolution_harness.install import ProjectionInstallError, install_projection

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    existing = target / ".agents/skills/architecture-review/SKILL.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("project-owned\n", encoding="utf-8")

    plan = install_projection(root, pack, target)
    assert plan["gate"] == "NO_GO"
    assert plan["collisions"][0]["reason"] == "unmanaged-target-exists"
    with pytest.raises(ProjectionInstallError, match="skill collision"):
        install_projection(root, pack, target, apply=True)
    assert existing.read_text(encoding="utf-8") == "project-owned\n"


def test_uninstall_refuses_modified_managed_skill(tmp_path: Path):
    from evolution_harness.install import ProjectionInstallError, install_projection, uninstall_projection

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    install_projection(root, pack, target, apply=True)
    skill = target / ".agents/skills/architecture-review/SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "manual edit\n", encoding="utf-8")

    plan = uninstall_projection(root, target)
    assert plan["gate"] == "NO_GO"
    with pytest.raises(ProjectionInstallError, match="managed file drift"):
        uninstall_projection(root, target, apply=True)
    assert skill.exists()


def test_install_rejects_poisoned_projection_skill_path(tmp_path: Path):
    from evolution_harness.install import ProjectionInstallError, install_projection

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    manifest_path = pack / "projection-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["generatedSkills"][0]["path"] = "../outside/SKILL.md"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ProjectionInstallError, match="unsafe projected skill path"):
        install_projection(root, pack, target)
