from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from capability_pack_test_support import retain_web_registration_fixture


EXTERNAL_CAPABILITY_ID = "workflow:web-high-fidelity:reference-driven-visual-fidelity"


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


def _external_pack(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    from evolution_harness.project import build_capability_lock
    from evolution_harness.projection import build_projection_pack
    from evolution_harness.resolver import resolve_design_context

    source_root = Path(__file__).parents[1]
    root = tmp_path / "harness"
    for name in ["core", "design", "runtime", "examples"]:
        shutil.copytree(source_root / name, root / name)
    retain_web_registration_fixture(root)
    project = root / "examples/project-fixture"
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
    resolved = resolve_design_context(
        root,
        project,
        intent="visual-reference-review",
        topic="web-fidelity",
        requested_output="review findings",
        runtime="CODEX",
    )
    build_projection_pack(root, project, resolved, runtime="CODEX")
    return root, project, source, root / "generated/projections/codex/project-fixture"


def test_external_pack_projection_apply_remains_disabled(tmp_path: Path):
    from evolution_harness.install import ProjectionInstallError, install_projection

    root, _, _, pack = _external_pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    before = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}

    with pytest.raises(
        ProjectionInstallError, match="automatic projection install is disabled"
    ):
        install_projection(root, pack, target, apply=True)

    after = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
    assert after == before


def _materialize_fixture_projection(root: Path, pack: Path, target: Path) -> Path:
    from evolution_harness import install
    from evolution_harness.generated import deterministic_json_bytes

    projection, inputs = install._projection_inputs(root, pack, target)
    for item in inputs:
        destination = target / item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(item["_sourceBytes"])
    manifest = target / install.INSTALL_MANIFEST_PATH
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_bytes(deterministic_json_bytes(install._persistent_manifest(projection, inputs)))
    return manifest


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


def test_install_and_uninstall_apply_are_disabled_without_target_writes(tmp_path: Path):
    from evolution_harness.install import ProjectionInstallError, install_projection, uninstall_projection

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    agents = target / "AGENTS.md"
    agents.write_text("# Keep me\n", encoding="utf-8")

    with pytest.raises(ProjectionInstallError, match="automatic projection install is disabled"):
        install_projection(root, pack, target, apply=True)
    with pytest.raises(ProjectionInstallError, match="automatic projection uninstall is disabled"):
        uninstall_projection(root, target, apply=True)
    assert not (target / ".agents").exists()
    assert not (target / ".agent-evolution").exists()
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
    with pytest.raises(ProjectionInstallError, match="automatic projection install is disabled"):
        install_projection(root, pack, target, apply=True)
    assert existing.read_text(encoding="utf-8") == "project-owned\n"


def test_uninstall_refuses_modified_managed_skill(tmp_path: Path):
    from evolution_harness.install import ProjectionInstallError, install_projection, uninstall_projection

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    _materialize_fixture_projection(root, pack, target)
    skill = target / ".agents/skills/architecture-review/SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "manual edit\n", encoding="utf-8")

    plan = uninstall_projection(root, target)
    assert plan["gate"] == "NO_GO"
    with pytest.raises(ProjectionInstallError, match="automatic projection uninstall is disabled"):
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

    with pytest.raises(ProjectionInstallError, match="canonical projection"):
        install_projection(root, pack, target)


def test_install_rejects_self_consistent_but_noncanonical_skill_bytes(tmp_path: Path):
    from evolution_harness.hashing import file_sha256
    from evolution_harness.install import ProjectionInstallError, install_projection

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    skill = pack / "skills/architecture-review/SKILL.md"
    skill.write_text("malicious but self-hashed\n", encoding="utf-8")
    manifest_path = pack / "projection-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["generatedFiles"]:
        if item["path"] == "skills/architecture-review/SKILL.md":
            item["sha256"] = file_sha256(skill)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ProjectionInstallError, match="canonical projection"):
        install_projection(root, pack, target)


def test_install_rejects_pack_outside_harness_generated_root(tmp_path: Path):
    from evolution_harness.install import ProjectionInstallError, install_projection

    root, _, pack = _pack(tmp_path)
    outside = tmp_path / "outside-pack"
    shutil.copytree(pack, outside)
    target = tmp_path / "target"
    target.mkdir()

    with pytest.raises(ProjectionInstallError, match="generated projections root"):
        install_projection(root, outside, target)


def test_install_rejects_symlinked_file_inside_canonical_projection(tmp_path: Path):
    from evolution_harness.install import ProjectionInstallError, install_projection

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    skill = pack / "skills/architecture-review/SKILL.md"
    outside = tmp_path / "outside-skill.md"
    outside.write_bytes(skill.read_bytes())
    skill.unlink()
    skill.symlink_to(outside)

    with pytest.raises(ProjectionInstallError, match="canonical projection"):
        install_projection(root, pack, target)


def test_uninstall_rejects_managed_skill_replaced_by_in_root_symlink(tmp_path: Path):
    from evolution_harness.install import ProjectionInstallError, install_projection, uninstall_projection

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    _materialize_fixture_projection(root, pack, target)
    skill = target / ".agents/skills/architecture-review/SKILL.md"
    unrelated = target / "unrelated.txt"
    unrelated.write_bytes(skill.read_bytes())
    skill.unlink()
    skill.symlink_to(unrelated)

    with pytest.raises(ProjectionInstallError, match="symlink"):
        uninstall_projection(root, target)
    assert unrelated.exists()


def test_install_legacy_transaction_marker_requires_manual_recovery_without_mutation(tmp_path: Path):
    from evolution_harness import install

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    victim = target / "src"
    victim.mkdir()
    sentinel = victim / "sentinel.txt"
    sentinel.write_text("preserve\n", encoding="utf-8")
    journal_path = target / install.INSTALL_TRANSACTION_PATH
    journal_path.parent.mkdir(parents=True)
    journal_path.write_text("legacy marker\n", encoding="utf-8")

    with pytest.raises(install.ProjectionInstallError, match="manual recovery"):
        install.install_projection(root, pack, target)

    assert sentinel.read_text(encoding="utf-8") == "preserve\n"
    assert journal_path.read_text(encoding="utf-8") == "legacy marker\n"


def test_install_and_uninstall_planners_reject_second_writer_for_same_target(tmp_path: Path):
    from evolution_harness import install
    from evolution_harness.process_lock import exclusive_process_lock, process_lock_identity

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    identity = process_lock_identity("projection-install", target)

    assert install.install_projection(root, pack, target)["mode"] == "DRY_RUN"
    with exclusive_process_lock(identity):
        with pytest.raises(install.ProjectionInstallError, match="concurrent projection install"):
            install.install_projection(root, pack, target)
        with pytest.raises(install.ProjectionInstallError, match="concurrent projection uninstall rejected"):
            install.uninstall_projection(root, target)
    assert not (target / ".agents").exists()
    with pytest.raises(install.ProjectionInstallError, match="automatic projection install is disabled"):
        install.install_projection(root, pack, target, apply=True)
    with pytest.raises(install.ProjectionInstallError, match="automatic projection uninstall is disabled"):
        install.uninstall_projection(root, target, apply=True)
    assert not (target / ".agents").exists()


def test_install_apply_shares_projection_pack_lock_with_builder(tmp_path: Path):
    from evolution_harness import install
    from evolution_harness.process_lock import exclusive_process_lock, process_lock_identity

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    pack_identity = process_lock_identity("projection-pack", pack)

    with exclusive_process_lock(pack_identity):
        with pytest.raises(install.ProjectionInstallError, match="projection pack.*locked|concurrent"):
            install.install_projection(root, pack, target)

    assert not (target / ".agents").exists()


def test_install_legacy_recovery_attestation_requires_manual_recovery_without_mutation(tmp_path: Path):
    from evolution_harness import install
    from evolution_harness.process_lock import (
        process_lock_identity,
        remove_recovery_attestation,
        write_recovery_attestation,
    )

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    identity = process_lock_identity("projection-install", target)
    write_recovery_attestation(identity, b"missing journal bytes\n", phase="PREPARED")
    try:
        with pytest.raises(install.ProjectionInstallError, match="manual recovery"):
            install.install_projection(root, pack, target)
    finally:
        remove_recovery_attestation(identity, missing_ok=True)

    assert not (target / ".agents").exists()
