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
    from evolution_harness.process_lock import process_lock_identity, recovery_attestation_phase

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
    assert recovery_attestation_phase(process_lock_identity("projection-install", target)) is None

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
    install_projection(root, pack, target, apply=True)
    skill = target / ".agents/skills/architecture-review/SKILL.md"
    unrelated = target / "unrelated.txt"
    unrelated.write_bytes(skill.read_bytes())
    skill.unlink()
    skill.symlink_to(unrelated)

    with pytest.raises(ProjectionInstallError, match="symlink"):
        uninstall_projection(root, target)
    assert unrelated.exists()


def test_install_keyboard_interrupt_rolls_back_using_persistent_journal(tmp_path: Path, monkeypatch):
    from evolution_harness import install
    from evolution_harness.anchored_fs import AnchoredRoot

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    original_write = AnchoredRoot.write_bytes
    interrupted = False

    def interrupt_manifest(self, relative: str, data: bytes, **kwargs):
        nonlocal interrupted
        if self.root == target and relative == install.INSTALL_MANIFEST_PATH and not interrupted:
            interrupted = True
            raise KeyboardInterrupt()
        return original_write(self, relative, data, **kwargs)

    monkeypatch.setattr(AnchoredRoot, "write_bytes", interrupt_manifest)
    with pytest.raises(KeyboardInterrupt):
        install.install_projection(root, pack, target, apply=True)

    assert not (target / ".agents/skills/architecture-review/SKILL.md").exists()
    assert not (target / ".agent-evolution/projection-install-manifest.json").exists()
    assert not (target / ".agent-evolution/projection-install-transaction.json").exists()


def test_install_reentry_recovers_prepared_journal_after_process_loss(tmp_path: Path):
    from evolution_harness import install
    from evolution_harness.generated import deterministic_json_bytes
    from evolution_harness.hashing import sha256_bytes

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    projection, inputs = install._projection_inputs(root, pack, target)
    source_bytes = inputs[0]["_sourceBytes"]
    destination = target / inputs[0]["path"]
    manifest_path = target / install.INSTALL_MANIFEST_PATH
    persistent = install._persistent_manifest(projection, inputs)
    install._begin_transaction(
        target,
        "INSTALL",
        [destination],
        manifest_path,
        after_sha256_by_path={inputs[0]["path"]: inputs[0]["sourceSha256"]},
        manifest_after_sha256=sha256_bytes(deterministic_json_bytes(persistent)),
    )
    from evolution_harness.anchored_fs import AnchoredRoot

    with AnchoredRoot(target) as filesystem:
        filesystem.write_bytes(destination.relative_to(target).as_posix(), source_bytes)

    with pytest.raises(install.ProjectionInstallError, match="explicit --apply"):
        install.install_projection(root, pack, target)
    assert destination.exists()

    result = install.install_projection(root, pack, target, apply=True)

    assert result["mode"] == "APPLY"
    assert destination.exists()
    assert manifest_path.exists()
    assert not (target / install.INSTALL_TRANSACTION_PATH).exists()


def test_install_recovery_refuses_file_created_after_prepared_transaction(tmp_path: Path):
    from evolution_harness import install
    from evolution_harness.generated import deterministic_json_bytes
    from evolution_harness.hashing import sha256_bytes

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    projection, inputs = install._projection_inputs(root, pack, target)
    destination = target / inputs[0]["path"]
    manifest_path = target / install.INSTALL_MANIFEST_PATH
    persistent = install._persistent_manifest(projection, inputs)
    install._begin_transaction(
        target,
        "INSTALL",
        [destination],
        manifest_path,
        after_sha256_by_path={inputs[0]["path"]: inputs[0]["sourceSha256"]},
        manifest_after_sha256=sha256_bytes(deterministic_json_bytes(persistent)),
    )

    project_owned_bytes = b"project-owned after process loss\n"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(project_owned_bytes)

    with pytest.raises(install.ProjectionInstallError, match="changed outside the failed transaction"):
        install.install_projection(root, pack, target, apply=True)

    assert destination.read_bytes() == project_owned_bytes
    assert not manifest_path.exists()
    assert (target / install.INSTALL_TRANSACTION_PATH).exists()


def test_install_recovery_rejects_forged_backup_directory_without_deleting_it(tmp_path: Path):
    from evolution_harness import install

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    victim = target / "src"
    victim.mkdir()
    sentinel = victim / "sentinel.txt"
    sentinel.write_text("preserve\n", encoding="utf-8")
    journal = {
        "schemaVersion": "projection-install-transaction/v1",
        "operation": "INSTALL",
        "phase": "COMMITTED",
        "backupDirectory": "src",
        "files": [],
        "manifest": {
            "existed": False,
            "backupPath": "src/install-manifest",
        },
    }
    journal_path = target / install.INSTALL_TRANSACTION_PATH
    journal_path.parent.mkdir(parents=True)
    journal_path.write_text(json.dumps(journal), encoding="utf-8")

    with pytest.raises(install.ProjectionInstallError, match="trusted recovery attestation"):
        install.install_projection(root, pack, target, apply=True)

    assert sentinel.read_text(encoding="utf-8") == "preserve\n"


def test_install_and_uninstall_apply_reject_second_writer_for_same_target(tmp_path: Path):
    from evolution_harness import install
    from evolution_harness.process_lock import exclusive_process_lock, process_lock_identity

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    identity = process_lock_identity("projection-install", target)

    assert install.install_projection(root, pack, target)["mode"] == "DRY_RUN"
    with exclusive_process_lock(identity):
        with pytest.raises(install.ProjectionInstallError, match="concurrent projection install"):
            install.install_projection(root, pack, target, apply=True)
    assert not (target / ".agents").exists()

    install.install_projection(root, pack, target, apply=True)
    managed = target / ".agents/skills/architecture-review/SKILL.md"
    with exclusive_process_lock(identity):
        with pytest.raises(install.ProjectionInstallError, match="concurrent projection uninstall rejected"):
            install.uninstall_projection(root, target, apply=True)
    assert managed.exists()


def test_install_apply_shares_projection_pack_lock_with_builder(tmp_path: Path):
    from evolution_harness import install
    from evolution_harness.process_lock import exclusive_process_lock, process_lock_identity

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    pack_identity = process_lock_identity("projection-pack", pack)

    with exclusive_process_lock(pack_identity):
        with pytest.raises(install.ProjectionInstallError, match="projection pack.*locked|concurrent"):
            install.install_projection(root, pack, target, apply=True)

    assert not (target / ".agents").exists()


def test_install_rejects_unattested_recovery_journal_without_mutating_target(tmp_path: Path):
    from evolution_harness import install

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    token = "b" * 32
    backup_directory = target / install.INSTALL_BACKUP_ROOT / token
    backup_directory.mkdir(parents=True)
    (backup_directory / "file-0").write_text("untrusted recovery bytes\n", encoding="utf-8")
    journal = {
        "schemaVersion": "projection-install-transaction/v1",
        "operation": "INSTALL",
        "phase": "PREPARED",
        "backupDirectory": f"{install.INSTALL_BACKUP_ROOT}/{token}",
        "files": [
            {
                "path": ".agents/skills/architecture-review/SKILL.md",
                "existed": True,
                "backupPath": f"{install.INSTALL_BACKUP_ROOT}/{token}/file-0",
            }
        ],
        "manifest": {
            "existed": False,
            "backupPath": f"{install.INSTALL_BACKUP_ROOT}/{token}/install-manifest",
        },
    }
    journal_path = target / install.INSTALL_TRANSACTION_PATH
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    destination = target / ".agents/skills/architecture-review/SKILL.md"

    with pytest.raises(install.ProjectionInstallError, match="attestation|trusted recovery"):
        install.install_projection(root, pack, target, apply=True)

    assert not destination.exists()


def test_install_recovery_rejects_tampered_attested_backup(tmp_path: Path):
    from evolution_harness import install
    from evolution_harness.anchored_fs import AnchoredRoot

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    install.install_projection(root, pack, target, apply=True)
    destination = target / ".agents/skills/architecture-review/SKILL.md"
    manifest_path = target / install.INSTALL_MANIFEST_PATH
    with AnchoredRoot(target) as filesystem:
        journal = install._begin_transaction(
            target,
            "UNINSTALL",
            [destination],
            manifest_path,
            filesystem,
            after_sha256_by_path={destination.relative_to(target).as_posix(): None},
            manifest_after_sha256=None,
        )
        filesystem.write_bytes(destination.relative_to(target).as_posix(), b"partial operation bytes\n")
        filesystem.write_bytes(journal["files"][0]["backupPath"], b"tampered backup bytes\n")

    with pytest.raises(install.ProjectionInstallError, match="backup hash mismatch"):
        install.install_projection(root, pack, target, apply=True)

    assert destination.read_bytes() == b"partial operation bytes\n"


def test_install_rejects_prepared_attestation_without_journal(tmp_path: Path):
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
        with pytest.raises(install.ProjectionInstallError, match="PREPARED recovery attestation has no journal"):
            install.install_projection(root, pack, target, apply=True)
    finally:
        remove_recovery_attestation(identity, missing_ok=True)

    assert not (target / ".agents").exists()


def test_install_apply_cannot_follow_parent_symlink_inserted_after_path_check(tmp_path: Path, monkeypatch):
    from evolution_harness import install

    root, _, pack = _pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    original_resolve = install.resolve_without_symlinks
    checked = 0

    def insert_symlink_after_check(root_path, relative, **kwargs):
        nonlocal checked
        result = original_resolve(root_path, relative, **kwargs)
        if relative == ".agents/skills/architecture-review/SKILL.md" and kwargs.get("label") == "skill install target":
            checked += 1
            if checked == 3:
                agents = target / ".agents"
                assert not agents.exists()
                agents.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(install, "resolve_without_symlinks", insert_symlink_after_check)

    with pytest.raises(install.ProjectionInstallError, match="symlink|anchored"):
        install.install_projection(root, pack, target, apply=True)

    assert not (outside / "skills/architecture-review/SKILL.md").exists()
