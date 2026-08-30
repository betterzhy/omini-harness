from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from capability_pack_test_support import retain_web_registration_fixture


EXTERNAL_CAPABILITY_ID = "workflow:web-high-fidelity:reference-driven-visual-fidelity"
PROFILE_CAPABILITY_ID = "skill:synthetic:profile-relocation"
PROFILE_ID = "toolchain-profile:test:canonical-relocation:v1"


def _profile_git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["/usr/bin/git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": "/var/empty",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    ).stdout.strip()


def _profile_make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() or os.access(path, os.X_OK) else 0o444)
    root.chmod(0o555)


def _profile_binding_record(toolchain_root: Path) -> dict[str, Any]:
    return {
        "schemaVersion": "capability-validator-toolchain-binding/v1",
        "profileId": PROFILE_ID,
        "commands": {
            "ruby": str(toolchain_root / "bin/ruby"),
            "rg": str(toolchain_root / "bin/rg"),
            "java": str(toolchain_root / "java/bin/java"),
            "javac": str(toolchain_root / "java/bin/javac"),
            "mvn": str(
                toolchain_root
                / "home/.m2/wrapper/dists/apache-maven/fixture/bin/mvn"
            ),
        },
        "directories": {
            "javaHome": str(toolchain_root / "java"),
            "mavenHome": str(
                toolchain_root / "home/.m2/wrapper/dists/apache-maven/fixture"
            ),
            "mavenRepository": str(toolchain_root / "home/.m2/repository"),
        },
    }


@dataclass(frozen=True)
class ProfileCanonicalOutputs:
    registry_bytes: bytes
    lock_bytes: bytes
    resolution_bytes: bytes
    projection_bytes: bytes
    install_plan_bytes: bytes
    projection_file_bytes: tuple[tuple[str, bytes], ...]
    source_revision: str
    source_digest: str
    registration_fingerprint: str
    lock_fingerprint: str
    selected_capability: dict[str, Any]
    projected_source: dict[str, Any]
    projected_skill: dict[str, Any]


@dataclass(frozen=True)
class ProfileProjectPair:
    first_root: Path
    second_root: Path
    first_binding_root: Path
    second_binding_root: Path
    profile_digest: str

    def build(self, root: Path) -> ProfileCanonicalOutputs:
        from evolution_harness.capability_pack_registry import (
            CapabilityVerificationSession,
            build_capability_pack_registry,
        )
        from evolution_harness.generated import deterministic_json_bytes
        from evolution_harness.hashing import canonical_json_bytes
        from evolution_harness.install import install_projection
        from evolution_harness.project import build_capability_lock
        from evolution_harness.projection import build_projection_pack
        from evolution_harness.resolver import resolve_design_context

        project = root / "examples/project-fixture"
        target = root / "install-target"
        target.mkdir()
        with CapabilityVerificationSession(
            root,
            allowed_capability_ids={PROFILE_CAPABILITY_ID},
        ) as session:
            registry = build_capability_pack_registry(
                root, write=False, verification_session=session
            )
            lock = build_capability_lock(
                root, project, write=True, verification_session=session
            )
            resolved = resolve_design_context(
                root,
                project,
                intent="architecture-review",
                topic="resolver-mvp",
                requested_output="review findings",
                runtime="CODEX",
                verification_session=session,
            )
            manifest = build_projection_pack(
                root,
                project,
                resolved,
                runtime="CODEX",
                verification_session=session,
            )
            pack = root / "generated/projections/codex/project-fixture"
            install_plan = install_projection(
                root,
                pack,
                target,
                verification_session=session,
            )

        locator_free_registry = deepcopy(registry)
        for entry in locator_free_registry["entries"]:
            entry["source"].pop("repositoryPath")
        external_lock = next(
            item
            for item in lock["capabilities"]
            if item["capabilityId"] == PROFILE_CAPABILITY_ID
        )
        selected = next(
            item
            for item in resolved["selectedCapabilities"]
            if item["id"] == PROFILE_CAPABILITY_ID
        )
        projected_source = next(
            item
            for item in manifest["sourceCapabilities"]
            if item["id"] == PROFILE_CAPABILITY_ID
        )
        projected_skill = next(
            item
            for item in manifest["generatedSkills"]
            if item["id"] == PROFILE_CAPABILITY_ID
        )
        projection_files = tuple(
            (path.relative_to(pack).as_posix(), path.read_bytes())
            for path in sorted(pack.rglob("*"))
            if path.is_file()
        )
        return ProfileCanonicalOutputs(
            registry_bytes=canonical_json_bytes(locator_free_registry),
            lock_bytes=canonical_json_bytes(lock),
            resolution_bytes=canonical_json_bytes(resolved),
            projection_bytes=deterministic_json_bytes(manifest),
            install_plan_bytes=canonical_json_bytes(install_plan),
            projection_file_bytes=projection_files,
            source_revision=registry["sourceRevision"],
            source_digest=external_lock["resolvedContentDigest"],
            registration_fingerprint=external_lock["registrationFingerprint"],
            lock_fingerprint=lock["lockFingerprint"],
            selected_capability=selected,
            projected_source=projected_source,
            projected_skill=projected_skill,
        )


def _create_profile_pack_source(base: Path) -> tuple[Path, dict[str, Any]]:
    from evolution_harness.capability_pack_registry import (
        _digest_entries,
        _selected_entries,
        _tree_entries,
    )

    source = base / "profile-pack-source"
    (source / "docs/history").mkdir(parents=True)
    (source / "skills/profile-relocation").mkdir(parents=True)
    (source / "scripts").mkdir()
    manifest = {
        "schemaVersion": "capability-pack/v1",
        "projectPackName": "profile-pack-source",
        "skillName": "profile-relocation",
        "displayName": "Synthetic Profile Relocation",
        "capabilityId": PROFILE_CAPABILITY_ID,
        "version": "1.0.0",
        "contentDigestContract": "capability-pack-content/v1",
        "contentRoots": ["docs", "skills"],
        "excludedContentRoots": ["docs/history"],
        "skillPath": "skills/profile-relocation/SKILL.md",
        "validator": {
            "kind": "FIXED_CANDIDATE_GATE",
            "path": "scripts/verify-capability-pack",
            "argumentsContract": "CANDIDATE_COMMIT_TREE",
        },
    }
    (source / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (source / "docs/evidence.txt").write_text(
        "canonical profile evidence\n", encoding="utf-8"
    )
    (source / "docs/history/ignored.txt").write_text("ignored\n", encoding="utf-8")
    (source / "skills/profile-relocation/SKILL.md").write_text(
        "---\nname: profile-relocation\ndescription: Synthetic profile relocation.\n---\n\n"
        "# Profile relocation\n",
        encoding="utf-8",
    )
    validator = source / "scripts/verify-capability-pack"
    validator.write_bytes(b"#!/bin/sh\nexit 0\n")
    validator.chmod(0o755)
    _profile_git(source, "init", "-q")
    _profile_git(source, "config", "user.name", "Profile Pair")
    _profile_git(source, "config", "user.email", "profile-pair@example.invalid")
    _profile_git(source, "add", "-A")
    _profile_git(source, "commit", "-qm", "test: profile relocation pack")
    commit = _profile_git(source, "rev-parse", "HEAD")
    tree = _profile_git(source, "rev-parse", "HEAD^{tree}")
    registration = {
        "schemaVersion": "capability-pack-registration/v1",
        "registrationId": "pack:profile-relocation",
        "capabilityId": PROFILE_CAPABILITY_ID,
        "packVersion": "1.0.0",
        "status": "ACTIVE",
        "distributionStatus": "LOCAL_ONLY",
        "source": {
            "kind": "LOCAL_GIT",
            "repositoryId": "profile-pack-source",
            "repositoryPath": str(source),
            "commit": commit,
            "tree": tree,
        },
        "contentDeclaration": {
            "kind": "HARNESS_DECLARED_MANIFEST",
            "manifest": manifest,
            "projectionContract": "SELF_CONTAINED_SKILL_BUNDLE",
        },
        "resolvedContentDigest": _digest_entries(
            source,
            _selected_entries(
                _tree_entries(source, commit),
                manifest,
                tracked_manifest_path=None,
            ),
        ),
        "validator": {
            "kind": "FIXED_CANDIDATE_GATE",
            "relativePath": "scripts/verify-capability-pack",
            "sha256": "sha256:" + hashlib.sha256(validator.read_bytes()).hexdigest(),
            "argumentsContract": "CANDIDATE_COMMIT_TREE",
            "environmentContract": "MANAGED_TOOLCHAIN_PROFILE",
        },
    }
    return source, registration


def _create_profile_toolchain(root: Path) -> Path:
    toolchain = root / ".worktrees/.capability-pack-cache/store/profile-toolchain"
    executable = b"#!/bin/sh\nexit 0\n"
    for relative in (
        "bin/ruby",
        "bin/rg",
        "java/bin/java",
        "java/bin/javac",
        "home/.m2/wrapper/dists/apache-maven/fixture/bin/mvn",
    ):
        path = toolchain / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(executable)
        path.chmod(0o555)
    (toolchain / "home/.m2/wrapper/dists/apache-maven/fixture/lib").mkdir()
    (toolchain / "home/.m2/wrapper/dists/apache-maven/fixture/lib/core.jar").write_bytes(
        b"maven-core"
    )
    repository = toolchain / "home/.m2/repository"
    (repository / "org/example/plugin/1.0").mkdir(parents=True)
    (repository / "org/example/plugin/1.0/plugin.jar").write_bytes(b"plugin")
    _profile_make_read_only(toolchain)
    return toolchain


def _profile_definition(toolchain: Path) -> dict[str, Any]:
    from evolution_harness.hashing import sha256_bytes
    from evolution_harness.toolchain_profile import directory_identity_digest

    command_digest = "sha256:" + sha256_bytes(b"#!/bin/sh\nexit 0\n")
    return {
        "schemaVersion": "capability-validator-toolchain-profile/v1",
        "profileId": PROFILE_ID,
        "environmentAdapter": "JAVA_MAVEN_OFFLINE_V1",
        "platform": {
            "os": platform.system().lower(),
            "architecture": platform.machine().lower(),
        },
        "commands": {
            name: {
                "artifactId": f"artifact:{name}:canonical-relocation",
                "fileName": name,
                "sha256": command_digest,
                "bindingPolicy": "HOST_ATTESTED",
            }
            for name in ("ruby", "rg", "java", "javac", "mvn")
        },
        "directories": {
            "javaHome": {
                "artifactId": "artifact:java:canonical-relocation",
                "sha256": directory_identity_digest(toolchain / "java"),
                "bindingPolicy": "HOST_ATTESTED",
            },
            "mavenHome": {
                "artifactId": "artifact:maven:canonical-relocation",
                "sha256": directory_identity_digest(
                    toolchain / "home/.m2/wrapper/dists/apache-maven/fixture"
                ),
                "bindingPolicy": "HOST_ATTESTED",
            },
            "mavenRepository": {
                "artifactId": "artifact:repository:canonical-relocation",
                "sha256": directory_identity_digest(
                    toolchain / "home/.m2/repository"
                ),
                "bindingPolicy": "HOST_ATTESTED",
            },
        },
        "relationships": {
            "javaHomeCommands": ["java", "javac"],
            "mavenHomeCommand": "mvn",
            "mavenRepositoryLayout": "DOT_M2_REPOSITORY",
        },
    }


def _create_profile_harness_root(
    root: Path,
    registration: dict[str, Any],
    profile: dict[str, Any],
    toolchain: Path,
) -> None:
    from evolution_harness.toolchain_profile import binding_path

    source = Path(__file__).parents[1]
    for name in ("core", "design", "runtime", "examples"):
        shutil.copytree(source / name, root / name)
    _profile_git(root, "init", "-q")
    (root / "core/registries/capability-packs.yaml").write_text(
        yaml.safe_dump([registration], sort_keys=False), encoding="utf-8"
    )
    (root / "core/registries/capability-validator-toolchains.yaml").write_text(
        yaml.safe_dump(
            {
                "schemaVersion": "capability-validator-toolchain-registry/v1",
                "artifacts": [],
                "profiles": [profile],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    project_binding_path = root / "examples/project-fixture/.agent-evolution/capabilities.yaml"
    project_binding = yaml.safe_load(project_binding_path.read_text(encoding="utf-8"))
    project_binding["capabilities"].append(PROFILE_CAPABILITY_ID)
    project_binding_path.write_text(
        yaml.safe_dump(project_binding, sort_keys=False), encoding="utf-8"
    )
    local_binding_path = binding_path(root, PROFILE_ID)
    local_binding_path.parent.mkdir(parents=True, exist_ok=True)
    local_binding_path.write_text(
        json.dumps(_profile_binding_record(toolchain), sort_keys=True),
        encoding="utf-8",
    )
    local_binding_path.chmod(0o444)


@pytest.fixture
def profile_project_pair(tmp_path: Path) -> ProfileProjectPair:
    from evolution_harness.toolchain_profile import profile_digest

    _, registration = _create_profile_pack_source(tmp_path)
    first_root = tmp_path / "first-harness"
    second_root = tmp_path / "second-harness"
    first_root.mkdir()
    second_root.mkdir()
    first_toolchain = _create_profile_toolchain(first_root)
    second_toolchain = _create_profile_toolchain(second_root)
    profile = _profile_definition(first_toolchain)
    digest = profile_digest(profile)
    registration["validator"]["toolchainProfile"] = {
        "profileId": PROFILE_ID,
        "profileDigest": digest,
    }
    _create_profile_harness_root(
        first_root, deepcopy(registration), deepcopy(profile), first_toolchain
    )
    _create_profile_harness_root(
        second_root, deepcopy(registration), deepcopy(profile), second_toolchain
    )
    return ProfileProjectPair(
        first_root=first_root,
        second_root=second_root,
        first_binding_root=first_toolchain,
        second_binding_root=second_toolchain,
        profile_digest=digest,
    )


def test_profile_binding_relocation_preserves_all_canonical_outputs(
    profile_project_pair: ProfileProjectPair,
):
    first = profile_project_pair.build(profile_project_pair.first_root)
    second = profile_project_pair.build(profile_project_pair.second_root)

    assert first.registry_bytes == second.registry_bytes
    assert first.lock_bytes == second.lock_bytes
    assert first.resolution_bytes == second.resolution_bytes
    assert first.projection_bytes == second.projection_bytes
    assert first.install_plan_bytes == second.install_plan_bytes
    assert first.projection_file_bytes == second.projection_file_bytes
    for payload in (
        first.registry_bytes,
        first.lock_bytes,
        first.resolution_bytes,
        first.projection_bytes,
        first.install_plan_bytes,
    ):
        assert str(profile_project_pair.first_binding_root).encode() not in payload
        assert str(profile_project_pair.second_binding_root).encode() not in payload
        assert b"ChatGPT.app" not in payload

    expected_profile = {
        "profileId": "toolchain-profile:test:canonical-relocation:v1",
        "profileDigest": profile_project_pair.profile_digest,
    }
    assert first.source_revision == second.source_revision
    assert first.source_digest == second.source_digest
    assert first.registration_fingerprint == second.registration_fingerprint
    assert first.lock_fingerprint == second.lock_fingerprint
    assert first.selected_capability == second.selected_capability
    assert first.selected_capability["selectedBecause"] == ["explicit-binding"]
    assert first.projected_source == second.projected_source
    assert first.projected_skill == second.projected_skill
    assert first.projected_source["validatorIdentity"]["toolchainProfile"] == (
        expected_profile
    )
    assert first.projected_skill["validatorIdentity"]["toolchainProfile"] == (
        expected_profile
    )
    assert first.projected_skill["resourceSetDigest"] == second.projected_skill[
        "resourceSetDigest"
    ]


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


def test_external_pack_install_dry_run_reuses_one_verification_session_without_plan_drift(
    tmp_path: Path,
):
    from evolution_harness.capability_pack_registry import CapabilityVerificationSession
    from evolution_harness.install import install_projection

    root, _, source_root, pack = _external_pack(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    expected_plan = install_projection(
        root,
        pack,
        target,
        source_root=source_root,
        apply=False,
    )

    with CapabilityVerificationSession(
        root,
        allowed_capability_ids={EXTERNAL_CAPABILITY_ID},
    ) as session:
        plan = install_projection(
            root,
            pack,
            target,
            source_root=source_root,
            apply=False,
            verification_session=session,
        )
        stats = session.stats

    assert plan == expected_plan
    assert plan["mode"] == "DRY_RUN"
    assert plan["gate"] == "PASS"
    assert not (target / ".agents").exists()
    assert stats.full_candidate_gate_count == 1
    assert stats.isolated_checkout_count == 1


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
