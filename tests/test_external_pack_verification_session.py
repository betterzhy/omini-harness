from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import threading
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from evolution_harness import capability_pack_registry
from evolution_harness.capability_pack_registry import (
    CapabilityVerificationSession,
    _get_verified_capability_pack,
    build_capability_pack_registry,
    get_registered_capability_pack,
)


def _git(repository: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    ).stdout.strip()


def _manifest(capability_id: str, name: str) -> dict[str, Any]:
    return {
        "schemaVersion": "capability-pack/v1",
        "projectPackName": name,
        "skillName": name,
        "displayName": f"Synthetic {name}",
        "capabilityId": capability_id,
        "version": "1.0.0",
        "contentDigestContract": "capability-pack-content/v1",
        "contentRoots": ["docs", "skills"],
        "excludedContentRoots": ["docs/history"],
        "skillPath": f"skills/{name}/SKILL.md",
        "validator": {
            "kind": "FIXED_CANDIDATE_GATE",
            "path": "scripts/verify-capability-pack",
            "argumentsContract": "CANDIDATE_COMMIT_TREE",
        },
    }


def _content_digest(source: Path, manifest: dict[str, Any]) -> str:
    tracked = [item for item in _git(source, "ls-files", "-z").split("\0") if item]
    selected = []
    for relative in tracked:
        active = any(
            relative == root or relative.startswith(root + "/")
            for root in manifest["contentRoots"]
        ) and not any(
            relative == root or relative.startswith(root + "/")
            for root in manifest["excludedContentRoots"]
        )
        if relative in {"VERSION", "capability-pack.yaml"} or active:
            selected.append(relative)
    digest = hashlib.sha256()
    for relative in sorted(selected, key=lambda value: value.encode("utf-8")):
        mode = _git(source, "ls-files", "--stage", "--", relative).split()[0]
        blob = (source / relative).read_bytes()
        for field in (
            relative.encode("utf-8"),
            mode.encode("ascii"),
            str(len(blob)).encode("ascii"),
            blob,
        ):
            digest.update(len(field).to_bytes(8, byteorder="big"))
            digest.update(field)
    return "sha256:" + digest.hexdigest()


def _create_source(base: Path, capability_id: str, name: str) -> tuple[Path, dict[str, Any]]:
    source = base / name
    (source / "docs/history").mkdir(parents=True)
    (source / f"skills/{name}").mkdir(parents=True)
    (source / "scripts").mkdir()
    manifest = _manifest(capability_id, name)
    (source / "capability-pack.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    (source / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (source / "docs/content.txt").write_text(f"{name} content\n", encoding="utf-8")
    (source / "docs/history/ignored.txt").write_text("ignored\n", encoding="utf-8")
    (source / f"skills/{name}/SKILL.md").write_text(
        f"# {name}\n", encoding="utf-8"
    )
    validator = source / "scripts/verify-capability-pack"
    validator.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "[ \"$#\" -eq 2 ]\n"
        "[ \"$(git rev-parse HEAD)\" = \"$1\" ]\n"
        "[ \"$(git rev-parse 'HEAD^{tree}')\" = \"$2\" ]\n",
        encoding="utf-8",
    )
    validator.chmod(0o755)
    _git(source, "init", "-q")
    _git(source, "config", "user.name", "Session Test")
    _git(source, "config", "user.email", "session-test@example.invalid")
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "test: synthetic pack")
    commit = _git(source, "rev-parse", "HEAD")
    tree = _git(source, "rev-parse", "HEAD^{tree}")
    registration = {
        "schemaVersion": "capability-pack-registration/v1",
        "registrationId": f"pack:{name}",
        "capabilityId": capability_id,
        "packVersion": "1.0.0",
        "status": "ACTIVE",
        "distributionStatus": "LOCAL_ONLY",
        "source": {
            "kind": "LOCAL_GIT",
            "repositoryId": name,
            "repositoryPath": str(source),
            "commit": commit,
            "tree": tree,
        },
        "resolvedContentDigest": _content_digest(source, manifest),
        "validator": {
            "kind": "FIXED_CANDIDATE_GATE",
            "relativePath": "scripts/verify-capability-pack",
            "sha256": "sha256:" + hashlib.sha256(validator.read_bytes()).hexdigest(),
            "argumentsContract": "CANDIDATE_COMMIT_TREE",
        },
    }
    return source, registration


def _write_registrations(root: Path, registrations: list[dict[str, Any]]) -> None:
    path = root / "core/registries/capability-packs.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(registrations, sort_keys=False), encoding="utf-8")


@dataclass
class PackHarness:
    root: Path
    registrations: list[dict[str, Any]]
    sources: dict[str, Path]

    @property
    def capability_id(self) -> str:
        return self.registrations[0]["capabilityId"]

    @property
    def second_capability_id(self) -> str:
        return self.registrations[1]["capabilityId"]

    def write(self) -> None:
        _write_registrations(self.root, self.registrations)


@dataclass
class ProfilePackHarness:
    root: Path
    capability_id: str
    profile_id: str
    profile_digest: str
    first_root: Path
    second_root: Path

    def binding_record(self, toolchain_root: Path) -> dict[str, Any]:
        return {
            "schemaVersion": "capability-validator-toolchain-binding/v1",
            "profileId": self.profile_id,
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
                    toolchain_root
                    / "home/.m2/wrapper/dists/apache-maven/fixture"
                ),
                "mavenRepository": str(toolchain_root / "home/.m2/repository"),
            },
        }

    @property
    def binding_file(self) -> Path:
        from evolution_harness.toolchain_profile import binding_path

        return binding_path(self.root, self.profile_id)

    def write_binding(self, toolchain_root: Path) -> None:
        path = self.binding_file
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.chmod(0o644)
        path.write_text(
            json.dumps(self.binding_record(toolchain_root), sort_keys=True),
            encoding="utf-8",
        )
        path.chmod(0o444)


def _make_profile_tree_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() or os.access(path, os.X_OK) else 0o444)
    root.chmod(0o555)


@pytest.fixture
def pack_harness(tmp_path: Path) -> PackHarness:
    root = tmp_path / "harness"
    schemas = root / "core/schemas"
    schemas.mkdir(parents=True)
    repository = Path(__file__).parents[1]
    for name in (
        "capability-pack-manifest.schema.json",
        "capability-pack-registration.schema.json",
    ):
        shutil.copy2(repository / "core/schemas" / name, schemas / name)
    first_id = "workflow:synthetic:first"
    second_id = "workflow:synthetic:second"
    first_source, first = _create_source(tmp_path, first_id, "synthetic-first")
    second_source, second = _create_source(tmp_path, second_id, "synthetic-second")
    harness = PackHarness(
        root=root,
        registrations=[first, second],
        sources={first_id: first_source, second_id: second_source},
    )
    harness.write()
    return harness


@pytest.fixture
def profile_pack_harness(
    pack_harness: PackHarness,
) -> ProfilePackHarness:
    from evolution_harness.hashing import canonical_json_bytes, sha256_bytes
    from evolution_harness.toolchain_profile import (
        directory_identity_digest,
        profile_digest,
    )

    root = pack_harness.root
    repository = Path(__file__).parents[1]
    for name in (
        "capability-validator-toolchain-registry.schema.json",
        "capability-validator-toolchain-binding.schema.json",
    ):
        shutil.copy2(repository / "core/schemas" / name, root / "core/schemas" / name)
    _git(root, "init", "-q")

    managed_store = root / ".worktrees/.capability-pack-cache/store"
    first_root = managed_store / "first"
    second_root = managed_store / "second"
    executable = b"#!/bin/sh\nexit 0\n"
    for relative in (
        "bin/ruby",
        "bin/rg",
        "java/bin/java",
        "java/bin/javac",
        "home/.m2/wrapper/dists/apache-maven/fixture/bin/mvn",
    ):
        path = first_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(executable)
        path.chmod(0o555)
    (first_root / "home/.m2/wrapper/dists/apache-maven/fixture/lib").mkdir()
    (first_root / "home/.m2/wrapper/dists/apache-maven/fixture/lib/core.jar").write_bytes(
        b"maven-core"
    )
    repository_root = first_root / "home/.m2/repository"
    (repository_root / "org/example/plugin/1.0").mkdir(parents=True)
    (repository_root / "org/example/plugin/1.0/plugin.jar").write_bytes(b"plugin")
    shutil.copytree(first_root, second_root)
    _make_profile_tree_read_only(first_root)
    _make_profile_tree_read_only(second_root)

    command_digest = "sha256:" + sha256_bytes(executable)
    artifact = {
        "artifactId": "artifact:ripgrep:test:darwin-arm64",
        "kind": "OFFICIAL_RELEASE_ARCHIVE",
        "platform": {
            "os": platform.system().lower(),
            "architecture": platform.machine().lower(),
        },
        "sourceUri": "https://example.invalid/ripgrep.tar.gz",
        "archiveFormat": "TAR_GZ",
        "archiveSha256": "sha256:" + "1" * 64,
        "extractedRoot": "ripgrep-test",
        "extractedFiles": {"rg": command_digest},
        "provenancePolicy": "OFFICIAL_GITHUB_RELEASE_ARCHIVE_SHA256",
    }
    artifact_digest = "sha256:" + sha256_bytes(canonical_json_bytes(artifact))
    profile_id = "toolchain-profile:test:darwin-arm64:v1"
    profile = {
        "schemaVersion": "capability-validator-toolchain-profile/v1",
        "profileId": profile_id,
        "environmentAdapter": "JAVA_MAVEN_OFFLINE_V1",
        "platform": artifact["platform"],
        "commands": {
            name: {
                "artifactId": (
                    artifact["artifactId"] if name == "rg" else f"artifact:{name}:test"
                ),
                "fileName": name,
                "sha256": command_digest,
                "bindingPolicy": (
                    "HARNESS_MANAGED_STORE" if name == "rg" else "HOST_ATTESTED"
                ),
                **({"artifactDigest": artifact_digest} if name == "rg" else {}),
            }
            for name in ("ruby", "rg", "java", "javac", "mvn")
        },
        "directories": {
            "javaHome": {
                "artifactId": "artifact:java:test",
                "sha256": directory_identity_digest(first_root / "java"),
                "bindingPolicy": "HOST_ATTESTED",
            },
            "mavenHome": {
                "artifactId": "artifact:maven:test",
                "sha256": directory_identity_digest(
                    first_root / "home/.m2/wrapper/dists/apache-maven/fixture"
                ),
                "bindingPolicy": "HOST_ATTESTED",
            },
            "mavenRepository": {
                "artifactId": "artifact:maven-repository:test",
                "sha256": directory_identity_digest(first_root / "home/.m2/repository"),
                "bindingPolicy": "HOST_ATTESTED",
            },
        },
        "relationships": {
            "javaHomeCommands": ["java", "javac"],
            "mavenHomeCommand": "mvn",
            "mavenRepositoryLayout": "DOT_M2_REPOSITORY",
        },
    }
    registry_path = root / "core/registries/capability-validator-toolchains.yaml"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        yaml.safe_dump(
            {
                "schemaVersion": "capability-validator-toolchain-registry/v1",
                "artifacts": [artifact],
                "profiles": [profile],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    digest = profile_digest(profile)
    registration = pack_harness.registrations[0]
    registration["validator"].update(
        {
            "environmentContract": "MANAGED_TOOLCHAIN_PROFILE",
            "toolchainProfile": {
                "profileId": profile_id,
                "profileDigest": digest,
            },
        }
    )
    pack_harness.write()
    harness = ProfilePackHarness(
        root=root,
        capability_id=pack_harness.capability_id,
        profile_id=profile_id,
        profile_digest=digest,
        first_root=first_root,
        second_root=second_root,
    )
    harness.write_binding(first_root)
    return harness


def _run_threads(*functions: Callable[[], object]) -> tuple[list[object], list[BaseException]]:
    results: list[object] = []
    failures: list[BaseException] = []
    mutex = threading.Lock()

    def run(function: Callable[[], object]) -> None:
        try:
            value = function()
            with mutex:
                results.append(value)
        except BaseException as exc:  # test captures concurrent failure publication
            with mutex:
                failures.append(exc)

    threads = [threading.Thread(target=run, args=(function,)) for function in functions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    return results, failures


def test_same_exact_pack_runs_one_gate_and_retains_one_checkout(
    pack_harness: PackHarness,
):
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as session:
        first = get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=session,
        )
        second = get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=session,
        )
        snapshot = session.stats

    assert first == second
    assert snapshot.full_candidate_gate_count == 1
    assert snapshot.isolated_checkout_count == 1
    assert snapshot.pack_reuse_hit_count == 1
    assert session.stats.active_use_lease_count == 0


def test_public_lookup_without_session_still_runs_one_full_gate(
    pack_harness: PackHarness, monkeypatch: pytest.MonkeyPatch
):
    real_gate = capability_pack_registry._run_candidate_gate
    gates = 0

    def counted_gate(*args, **kwargs):
        nonlocal gates
        gates += 1
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", counted_gate)

    result = get_registered_capability_pack(
        pack_harness.root,
        pack_harness.capability_id,
    )

    assert result["capabilityId"] == pack_harness.capability_id
    assert gates == 1


def test_profile_public_lookup_persists_no_verification_result(
    profile_pack_harness: ProfilePackHarness,
):
    result = get_registered_capability_pack(
        profile_pack_harness.root,
        profile_pack_harness.capability_id,
    )

    assert result["validator"]["toolchainProfile"] == {
        "profileId": "toolchain-profile:test:darwin-arm64:v1",
        "profileDigest": profile_pack_harness.profile_digest,
    }
    forbidden = (
        b"full_candidate_gate_count",
        b"verified_pack_count",
        b"session_token",
        b"reuse_hit_count",
    )
    inspected = [profile_pack_harness.binding_file]
    inspected.extend(
        path
        for path in (
            profile_pack_harness.root
            / ".worktrees/.capability-pack-cache/store"
        ).rglob("*")
        if path.is_file()
    )
    assert inspected
    for path in inspected:
        data = path.read_bytes()
        assert all(marker not in data for marker in forbidden)


def test_stats_are_new_immutable_snapshots(pack_harness: PackHarness):
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as session:
        get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=session,
        )
        before_reuse = session.stats
        with pytest.raises(TypeError):
            before_reuse.by_pack["forged"] = {}  # type: ignore[index]
        get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=session,
        )
        after_reuse = session.stats
    assert before_reuse is not after_reuse
    assert before_reuse.pack_reuse_hit_count == 0
    assert after_reuse.pack_reuse_hit_count == 1


def test_session_rejects_unlisted_capability_and_different_root_before_gate(
    pack_harness: PackHarness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    gates = 0

    def unexpected_gate(*args, **kwargs):
        nonlocal gates
        gates += 1
        raise AssertionError("Gate must not run")

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", unexpected_gate)
    other_root = tmp_path / "other-harness"
    shutil.copytree(pack_harness.root, other_root)
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as session:
        with pytest.raises(ValueError, match="not allowed"):
            get_registered_capability_pack(
                pack_harness.root,
                pack_harness.second_capability_id,
                verification_session=session,
            )
        with pytest.raises(ValueError, match="repository root"):
            get_registered_capability_pack(
                other_root,
                pack_harness.capability_id,
                verification_session=session,
            )
    assert gates == 0


def test_registry_rejects_unlisted_declared_capability_before_any_gate(
    pack_harness: PackHarness, monkeypatch: pytest.MonkeyPatch
):
    gates = 0

    def unexpected_gate(*args, **kwargs):
        nonlocal gates
        gates += 1
        raise AssertionError("Gate must not run")

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", unexpected_gate)
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as session:
        with pytest.raises(ValueError, match="not allowed"):
            build_capability_pack_registry(
                pack_harness.root,
                write=False,
                verification_session=session,
            )
    assert gates == 0


def test_parent_session_close_drains_child_validation_and_rejects_success(
    pack_harness: PackHarness, monkeypatch: pytest.MonkeyPatch
):
    first = pack_harness.registrations[0]
    first["status"] = "INACTIVE"
    second = deepcopy(first)
    second["registrationId"] = "pack:synthetic-first-legacy"
    pack_harness.registrations = [first, second]
    pack_harness.write()
    real_gate = capability_pack_registry._run_candidate_gate
    gate_entered = threading.Event()
    release = threading.Event()

    def blocked_gate(*args, **kwargs):
        gate_entered.set()
        assert release.wait(timeout=5)
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", blocked_gate)
    session = CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    )
    failures: list[BaseException] = []
    builder = threading.Thread(
        target=lambda: _capture_failure(
            lambda: build_capability_pack_registry(
                pack_harness.root,
                write=False,
                verification_session=session,
            ),
            failures,
        )
    )
    builder.start()
    assert gate_entered.wait(timeout=5)
    closed = threading.Event()
    closer = threading.Thread(target=lambda: (session.close(), closed.set()))
    closer.start()
    assert not closed.wait(timeout=0.05)
    release.set()
    builder.join(timeout=5)
    closer.join(timeout=5)
    assert len(failures) == 1
    assert "session is closing" in str(failures[0])
    assert closed.is_set()
    assert session.stats.active_use_lease_count == 0


@pytest.mark.parametrize(
    ("failure_phase", "expected_error"),
    [
        ("gate", ValueError),
        ("recheck", RuntimeError),
        ("cleanup", ExceptionGroup),
    ],
)
def test_child_validation_failure_poisons_parent_and_prevents_verified_reuse(
    pack_harness: PackHarness,
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
    expected_error: type[BaseException],
):
    second_capability_id = pack_harness.second_capability_id
    session = CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={
            pack_harness.capability_id,
            second_capability_id,
        },
    )
    _get_verified_capability_pack(
        pack_harness.root,
        second_capability_id,
        verification_session=session,
    )
    first = pack_harness.registrations[0]
    first["status"] = "INACTIVE"
    legacy = deepcopy(first)
    legacy["registrationId"] = "pack:synthetic-first-legacy"
    pack_harness.registrations = [first, legacy, pack_harness.registrations[1]]
    pack_harness.write()

    with monkeypatch.context() as child_patch:
        if failure_phase == "gate":
            child_patch.setattr(
                capability_pack_registry,
                "_run_candidate_gate",
                lambda *args, **kwargs: subprocess.CompletedProcess(
                    args[0], 31, b"", b"child gate failed"
                ),
            )
        elif failure_phase == "recheck":
            real_recheck = capability_pack_registry._recheck_verified_pack_witness

            def failed_recheck(pack):
                real_recheck(pack)
                raise RuntimeError("child recheck failed")

            child_patch.setattr(
                capability_pack_registry,
                "_recheck_verified_pack_witness",
                failed_recheck,
            )
        else:
            real_checkout = capability_pack_registry._isolated_fixed_checkout

            @contextmanager
            def failed_cleanup(*args, **kwargs):
                with real_checkout(*args, **kwargs) as checkout:
                    yield checkout
                raise RuntimeError("child cleanup failed")

            child_patch.setattr(
                capability_pack_registry,
                "_isolated_fixed_checkout",
                failed_cleanup,
            )

        with pytest.raises(expected_error):
            build_capability_pack_registry(
                pack_harness.root,
                write=False,
                verification_session=session,
            )

    with pytest.raises(ValueError, match="session is failed"):
        get_registered_capability_pack(
            pack_harness.root,
            second_capability_id,
            verification_session=session,
        )
    session.close()


def test_parent_poisoned_while_child_only_build_is_in_flight_returns_no_success(
    pack_harness: PackHarness, monkeypatch: pytest.MonkeyPatch
):
    second_capability_id = pack_harness.second_capability_id
    session = CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={
            pack_harness.capability_id,
            second_capability_id,
        },
    )
    prior = _get_verified_capability_pack(
        pack_harness.root,
        second_capability_id,
        verification_session=session,
    )
    first = pack_harness.registrations[0]
    first["status"] = "INACTIVE"
    legacy = deepcopy(first)
    legacy["registrationId"] = "pack:synthetic-first-legacy"
    pack_harness.registrations = [first, legacy]
    pack_harness.write()
    real_gate = capability_pack_registry._run_candidate_gate
    gate_entered = threading.Event()
    release_gate = threading.Event()

    def blocked_gate(*args, **kwargs):
        gate_entered.set()
        assert release_gate.wait(timeout=5)
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", blocked_gate)
    results: list[dict[str, Any]] = []
    failures: list[BaseException] = []

    def build() -> None:
        try:
            results.append(
                build_capability_pack_registry(
                    pack_harness.root,
                    write=False,
                    verification_session=session,
                )
            )
        except BaseException as exc:
            failures.append(exc)

    builder = threading.Thread(target=build)
    builder.start()
    assert gate_entered.wait(timeout=5)
    with pytest.raises(ValueError, match="active registration identity drift"):
        prior.recheck()
    release_gate.set()
    builder.join(timeout=10)
    assert not builder.is_alive()
    assert not results
    assert len(failures) == 1
    assert "session is failed" in str(failures[0])
    session.close()


def test_verified_pack_rejects_foreign_session_and_use_after_close(
    pack_harness: PackHarness,
):
    owner = CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    )
    foreign = CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    )
    verified = _get_verified_capability_pack(
        pack_harness.root,
        pack_harness.capability_id,
        verification_session=owner,
    )
    with pytest.raises(ValueError, match="foreign"):
        foreign._read_verified_blob(verified, "docs/content.txt")
    owner.close()
    with pytest.raises(ValueError, match="closed"):
        verified.read_blob("docs/content.txt")
    with pytest.raises(ValueError, match="closed"):
        verified.recheck()
    foreign.close()


def test_failed_gate_is_not_reused_and_poisoned_session_rejects_retry(
    pack_harness: PackHarness, monkeypatch: pytest.MonkeyPatch
):
    real_gate = capability_pack_registry._run_candidate_gate
    attempts = 0
    checkout_paths: list[Path] = []

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        checkout_paths.append(kwargs["cwd"])
        if attempts == 1:
            completed = real_gate(*args, **kwargs)
            return subprocess.CompletedProcess(completed.args, 23, completed.stdout, completed.stderr)
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", fail_once)
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as failed:
        with pytest.raises(ValueError, match="candidate Gate failed"):
            get_registered_capability_pack(
                pack_harness.root,
                pack_harness.capability_id,
                verification_session=failed,
            )
        with pytest.raises(ValueError, match="failed"):
            get_registered_capability_pack(
                pack_harness.root,
                pack_harness.capability_id,
                verification_session=failed,
            )
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as fresh:
        get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=fresh,
        )
    assert attempts == 2
    assert checkout_paths
    assert all(not path.exists() for path in checkout_paths)


def test_same_key_concurrent_requests_publish_one_success(
    pack_harness: PackHarness, monkeypatch: pytest.MonkeyPatch
):
    real_gate = capability_pack_registry._run_candidate_gate
    both_callers = threading.Barrier(2)
    gate_entered = threading.Event()
    release_gate = threading.Event()
    gates = 0

    def blocked_gate(*args, **kwargs):
        nonlocal gates
        gates += 1
        gate_entered.set()
        assert release_gate.wait(timeout=5)
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", blocked_gate)
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as session:
        def lookup():
            both_callers.wait(timeout=5)
            return get_registered_capability_pack(
                pack_harness.root,
                pack_harness.capability_id,
                verification_session=session,
            )

        coordinator = threading.Thread(
            target=lambda: (gate_entered.wait(timeout=5), release_gate.set())
        )
        coordinator.start()
        results, failures = _run_threads(lookup, lookup)
        coordinator.join(timeout=5)
    assert not failures
    assert len(results) == 2
    assert results[0] == results[1]
    assert gates == 1


def test_same_key_concurrent_failure_is_published_to_all_waiters(
    pack_harness: PackHarness, monkeypatch: pytest.MonkeyPatch
):
    both_callers = threading.Barrier(2)
    gate_entered = threading.Event()
    release_gate = threading.Event()
    gates = 0

    def failed_gate(*args, **kwargs):
        nonlocal gates
        gates += 1
        gate_entered.set()
        assert release_gate.wait(timeout=5)
        return subprocess.CompletedProcess(args[0], 29, b"", b"failed")

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", failed_gate)
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as session:
        def lookup():
            both_callers.wait(timeout=5)
            return get_registered_capability_pack(
                pack_harness.root,
                pack_harness.capability_id,
                verification_session=session,
            )

        coordinator = threading.Thread(
            target=lambda: (gate_entered.wait(timeout=5), release_gate.set())
        )
        coordinator.start()
        results, failures = _run_threads(lookup, lookup)
        coordinator.join(timeout=5)
    assert not results
    assert len(failures) == 2
    assert all("candidate Gate failed" in str(failure) for failure in failures)
    assert gates == 1


def test_different_pack_keys_validate_concurrently(
    pack_harness: PackHarness, monkeypatch: pytest.MonkeyPatch
):
    real_gate = capability_pack_registry._run_candidate_gate
    gates_meet = threading.Barrier(2)
    gates = 0
    mutex = threading.Lock()

    def concurrent_gate(*args, **kwargs):
        nonlocal gates
        with mutex:
            gates += 1
        gates_meet.wait(timeout=5)
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", concurrent_gate)
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={
            pack_harness.capability_id,
            pack_harness.second_capability_id,
        },
    ) as session:
        results, failures = _run_threads(
            lambda: get_registered_capability_pack(
                pack_harness.root,
                pack_harness.capability_id,
                verification_session=session,
            ),
            lambda: get_registered_capability_pack(
                pack_harness.root,
                pack_harness.second_capability_id,
                verification_session=session,
            ),
        )
    assert not failures
    assert len(results) == 2
    assert gates == 2


def test_close_drains_different_key_verification_and_cleans_both_checkouts(
    pack_harness: PackHarness, monkeypatch: pytest.MonkeyPatch
):
    real_gate = capability_pack_registry._run_candidate_gate
    both_gates = threading.Barrier(3)
    release = threading.Event()
    checkout_paths: list[Path] = []
    mutex = threading.Lock()

    def blocked_gate(*args, **kwargs):
        with mutex:
            checkout_paths.append(kwargs["cwd"])
        both_gates.wait(timeout=5)
        assert release.wait(timeout=5)
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", blocked_gate)
    session = CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={
            pack_harness.capability_id,
            pack_harness.second_capability_id,
        },
    )
    results: list[object] = []
    failures: list[BaseException] = []

    def lookup(capability_id: str) -> None:
        try:
            results.append(
                get_registered_capability_pack(
                    pack_harness.root,
                    capability_id,
                    verification_session=session,
                )
            )
        except BaseException as exc:
            failures.append(exc)

    users = [
        threading.Thread(target=lookup, args=(capability_id,))
        for capability_id in (
            pack_harness.capability_id,
            pack_harness.second_capability_id,
        )
    ]
    for user in users:
        user.start()
    both_gates.wait(timeout=5)
    closed = threading.Event()
    closer = threading.Thread(target=lambda: (session.close(), closed.set()))
    closer.start()
    assert not closed.wait(timeout=0.05)
    release.set()
    for user in users:
        user.join(timeout=5)
        assert not user.is_alive()
    closer.join(timeout=5)
    assert not closer.is_alive()
    assert not results
    assert len(failures) == 2
    assert session.stats.active_use_lease_count == 0
    assert len(checkout_paths) == 2
    assert all(not path.exists() for path in checkout_paths)


@pytest.mark.parametrize("operation", ["read", "recheck"])
def test_close_waits_for_active_verified_pack_use(
    pack_harness: PackHarness,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
):
    session = CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    )
    verified = _get_verified_capability_pack(
        pack_harness.root,
        pack_harness.capability_id,
        verification_session=session,
    )
    entered = threading.Event()
    release = threading.Event()
    real_recheck = capability_pack_registry._recheck_verified_pack_witness

    def blocked_recheck(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return real_recheck(*args, **kwargs)

    monkeypatch.setattr(
        capability_pack_registry, "_recheck_verified_pack_witness", blocked_recheck
    )
    failures: list[BaseException] = []
    action = (
        lambda: verified.read_blob("docs/content.txt")
        if operation == "read"
        else verified.recheck()
    )
    user = threading.Thread(target=lambda: _capture_failure(action, failures))
    user.start()
    assert entered.wait(timeout=5)
    closed = threading.Event()
    closer = threading.Thread(target=lambda: (session.close(), closed.set()))
    closer.start()
    assert not closed.wait(timeout=0.05)
    release.set()
    user.join(timeout=5)
    closer.join(timeout=5)
    assert not failures
    assert closed.is_set()
    assert session.stats.active_use_lease_count == 0


def _capture_failure(function: Callable[[], object], failures: list[BaseException]) -> None:
    try:
        function()
    except BaseException as exc:
        failures.append(exc)


def test_close_attempts_all_cleanup_owners_and_aggregates_failures(
    pack_harness: PackHarness,
):
    session = CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={
            pack_harness.capability_id,
            pack_harness.second_capability_id,
        },
    )
    first_verified = _get_verified_capability_pack(
        pack_harness.root,
        pack_harness.capability_id,
        verification_session=session,
    )
    _get_verified_capability_pack(
        pack_harness.root,
        pack_harness.second_capability_id,
        verification_session=session,
    )
    calls: list[str] = []
    actual_cleanups = list(session._cleanups)

    def fail(name: str, cleanup: Callable[[], object]):
        cleanup()
        calls.append(name)
        raise RuntimeError(name)

    session._cleanups = [
        lambda: fail("first", actual_cleanups[0]),
        lambda: fail("second", actual_cleanups[1]),
    ]
    with pytest.raises(ExceptionGroup) as raised:
        session.close()
    assert calls == ["second", "first"]
    assert {str(error) for error in raised.value.exceptions} == {"first", "second"}
    assert session.stats.active_use_lease_count == 0
    with pytest.raises(ValueError, match="closed"):
        first_verified.read_blob("docs/content.txt")
    session.close()


def test_registration_results_are_defensive_and_blob_reads_use_retained_checkout(
    pack_harness: PackHarness, monkeypatch: pytest.MonkeyPatch
):
    blob_roots: list[Path] = []
    real_blob = capability_pack_registry._blob

    def observed_blob(root: Path, object_id: str) -> bytes:
        blob_roots.append(root)
        return real_blob(root, object_id)

    monkeypatch.setattr(capability_pack_registry, "_blob", observed_blob)
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as session:
        verified = _get_verified_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=session,
        )
        first = verified.registration_copy()
        first["source"]["commit"] = "0" * 40
        second = verified.registration_copy()
        data = verified.read_blob("docs/content.txt")
        blobs = verified.read_blobs()
        lock_entry = verified.lock_entry_copy()
        lock_entry["manifest"]["displayName"] = "mutated defensive copy"
        next_lock_entry = verified.lock_entry_copy()
        checkout = verified._checkout_root

    assert second["source"]["commit"] != "0" * 40
    assert data == b"synthetic-first content\n"
    assert blobs["docs/content.txt"] == data
    assert set(blobs) == {
        "VERSION",
        "capability-pack.yaml",
        "docs/content.txt",
        "skills/synthetic-first/SKILL.md",
    }
    assert next_lock_entry["sourceKind"] == "EXTERNAL_CAPABILITY_PACK"
    assert next_lock_entry["registrationFingerprint"] == (
        capability_pack_registry._locator_bound_blob_access_fingerprint(second)
    )
    assert next_lock_entry["manifest"]["displayName"] == "Synthetic synthetic-first"
    assert checkout in blob_roots
    assert not checkout.exists()


def test_changed_canonical_identity_poisons_session_and_fresh_session_revalidates(
    pack_harness: PackHarness, monkeypatch: pytest.MonkeyPatch
):
    real_gate = capability_pack_registry._run_candidate_gate
    gates = 0

    def counted_gate(*args, **kwargs):
        nonlocal gates
        gates += 1
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", counted_gate)
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as session:
        get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=session,
        )
        pack_harness.registrations[0]["validator"]["timeoutSeconds"] = 301
        pack_harness.write()
        with pytest.raises(ValueError, match="identity changed"):
            get_registered_capability_pack(
                pack_harness.root,
                pack_harness.capability_id,
                verification_session=session,
            )
        with pytest.raises(ValueError, match="failed"):
            get_registered_capability_pack(
                pack_harness.root,
                pack_harness.capability_id,
                verification_session=session,
            )
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as fresh:
        get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=fresh,
        )
    assert gates == 2


@pytest.mark.parametrize(
    "mutation",
    ["source-commit", "source-tree", "content-digest", "status", "validator-digest"],
)
def test_each_changed_identity_fact_poisons_session_and_is_not_inherited(
    pack_harness: PackHarness,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
):
    real_gate = capability_pack_registry._run_candidate_gate
    gates = 0

    def counted_gate(*args, **kwargs):
        nonlocal gates
        gates += 1
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", counted_gate)
    original = deepcopy(pack_harness.registrations[0])
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as session:
        get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=session,
        )
        changed = pack_harness.registrations[0]
        if mutation == "source-commit":
            changed["source"]["commit"] = "a" * 40
        elif mutation == "source-tree":
            changed["source"]["tree"] = "b" * 40
        elif mutation == "content-digest":
            changed["resolvedContentDigest"] = "sha256:" + "c" * 64
        elif mutation == "status":
            changed["status"] = "INACTIVE"
        else:
            changed["validator"]["sha256"] = "sha256:" + "d" * 64
        pack_harness.write()
        with pytest.raises((KeyError, ValueError)):
            get_registered_capability_pack(
                pack_harness.root,
                pack_harness.capability_id,
                verification_session=session,
            )
        with pytest.raises(ValueError, match="failed"):
            session.__enter__()
        assert session.stats.full_candidate_gate_count == 1
    pack_harness.registrations[0] = original
    pack_harness.write()
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as fresh:
        get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=fresh,
        )
    assert gates == 2


def test_validator_abi_change_poisons_session_and_fresh_session_revalidates(
    pack_harness: PackHarness, monkeypatch: pytest.MonkeyPatch
):
    real_gate = capability_pack_registry._run_candidate_gate
    gates = 0

    def counted_gate(*args, **kwargs):
        nonlocal gates
        gates += 1
        return real_gate(*args, **kwargs)

    assert capability_pack_registry.CAPABILITY_PACK_VALIDATION_ABI == "v2"
    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", counted_gate)
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as session:
        get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=session,
        )
        monkeypatch.setattr(
            capability_pack_registry, "CAPABILITY_PACK_VALIDATION_ABI", "v1"
        )
        with pytest.raises(ValueError, match="identity changed"):
            get_registered_capability_pack(
                pack_harness.root,
                pack_harness.capability_id,
                verification_session=session,
            )
    monkeypatch.setattr(capability_pack_registry, "CAPABILITY_PACK_VALIDATION_ABI", "v2")
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as fresh:
        get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=fresh,
        )
    assert gates == 2


def test_changed_registration_id_for_same_capability_is_not_a_second_session_key(
    pack_harness: PackHarness,
):
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as session:
        get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=session,
        )
        pack_harness.registrations[0]["registrationId"] = "pack:replacement-first"
        pack_harness.write()
        with pytest.raises(ValueError, match="identity changed"):
            get_registered_capability_pack(
                pack_harness.root,
                pack_harness.capability_id,
                verification_session=session,
            )
        assert session.stats.full_candidate_gate_count == 1
        assert session.stats.isolated_checkout_count == 1


def test_verified_active_pack_recheck_rejects_new_duplicate_active_registration(
    pack_harness: PackHarness,
):
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as session:
        verified = _get_verified_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=session,
        )
        duplicate = deepcopy(pack_harness.registrations[0])
        duplicate["registrationId"] = "pack:duplicate-active-first"
        pack_harness.registrations.append(duplicate)
        pack_harness.write()
        with pytest.raises(ValueError, match="duplicate active capability pack ID"):
            verified.recheck()
        with pytest.raises(ValueError, match="failed"):
            verified.read_blob("docs/content.txt")


def test_verified_inactive_pack_recheck_rejects_duplicate_registration_identity(
    pack_harness: PackHarness,
):
    registration = pack_harness.registrations[0]
    registration["status"] = "INACTIVE"
    pack_harness.registrations = [registration]
    pack_harness.write()
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as session:
        verified = _get_verified_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=session,
            _registration=registration,
        )
        pack_harness.registrations.append(deepcopy(registration))
        pack_harness.write()
        with pytest.raises(ValueError, match="registration not found or ambiguous"):
            verified.recheck()


def test_locator_relocation_fails_open_session_but_new_session_runs_full_gate(
    pack_harness: PackHarness,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    real_gate = capability_pack_registry._run_candidate_gate
    gates = 0

    def counted_gate(*args, **kwargs):
        nonlocal gates
        gates += 1
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", counted_gate)
    original = pack_harness.registrations[0]
    original_fingerprint = capability_pack_registry._registration_fingerprint(original)
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as session:
        get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=session,
        )
        relocated = tmp_path / "relocated-first"
        _git(
            tmp_path,
            "clone",
            "--quiet",
            "--no-hardlinks",
            str(pack_harness.sources[pack_harness.capability_id]),
            str(relocated),
        )
        _git(relocated, "checkout", "--quiet", "--detach", original["source"]["commit"])
        original["source"]["repositoryPath"] = str(relocated)
        pack_harness.write()
        assert capability_pack_registry._registration_fingerprint(original) == (
            original_fingerprint
        )
        with pytest.raises(ValueError, match="locator identity drift"):
            get_registered_capability_pack(
                pack_harness.root,
                pack_harness.capability_id,
                verification_session=session,
            )
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as fresh:
        get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=fresh,
        )
    assert gates == 2


@pytest.mark.parametrize(
    "mutation",
    [
        "source-commit",
        "source-tree",
        "content-digest",
        "canonical-registration",
        "validator-digest",
        "expected-toolchain",
    ],
)
def test_pack_key_binds_every_registered_trust_fact(
    pack_harness: PackHarness, mutation: str
):
    registration = deepcopy(pack_harness.registrations[0])
    original = capability_pack_registry._pack_verification_key(
        registration, "sha256:" + "1" * 64
    )
    changed = deepcopy(registration)
    if mutation == "source-commit":
        changed["source"]["commit"] = "a" * 40
    elif mutation == "source-tree":
        changed["source"]["tree"] = "b" * 40
    elif mutation == "content-digest":
        changed["resolvedContentDigest"] = "sha256:" + "c" * 64
    elif mutation == "canonical-registration":
        changed["status"] = "INACTIVE"
    elif mutation == "validator-digest":
        changed["validator"]["sha256"] = "sha256:" + "d" * 64
    else:
        changed["validator"]["toolchain"] = {
            "expectedIdentity": "sha256:" + "e" * 64
        }
    assert capability_pack_registry._pack_verification_key(
        changed, "sha256:" + "1" * 64
    ) != original


def test_pack_key_binds_manifest_abi_and_platform_but_excludes_locator(
    pack_harness: PackHarness, monkeypatch: pytest.MonkeyPatch
):
    registration = deepcopy(pack_harness.registrations[0])
    original = capability_pack_registry._pack_verification_key(
        registration, "sha256:" + "1" * 64
    )
    relocated = deepcopy(registration)
    relocated["source"]["repositoryPath"] = "/different/locator"
    assert capability_pack_registry._pack_verification_key(
        relocated, "sha256:" + "1" * 64
    ) == original
    assert capability_pack_registry._pack_verification_key(
        registration, "sha256:" + "2" * 64
    ) != original
    monkeypatch.setattr(capability_pack_registry, "CAPABILITY_PACK_VALIDATION_ABI", "v1")
    assert capability_pack_registry._pack_verification_key(
        registration, "sha256:" + "1" * 64
    ) != original


@pytest.mark.parametrize(
    "mutation",
    [
        "profile-id",
        "profile-digest",
        "profile-platform",
        "profile-command-digest",
        "profile-directory-digest",
        "managed-artifact-manifest-digest",
    ],
)
def test_profile_identity_mutations_change_key_or_fail_loading_before_gate(
    profile_pack_harness: ProfilePackHarness,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
):
    registration_path = (
        profile_pack_harness.root / "core/registries/capability-packs.yaml"
    )
    registrations = yaml.safe_load(registration_path.read_text(encoding="utf-8"))
    registration = registrations[0]
    original_key = capability_pack_registry._pack_verification_key(
        registration, "sha256:" + "1" * 64
    )
    if mutation == "profile-id":
        registration["validator"]["toolchainProfile"]["profileId"] = (
            "toolchain-profile:test:darwin-arm64:v2"
        )
        assert capability_pack_registry._pack_verification_key(
            registration, "sha256:" + "1" * 64
        ) != original_key
        return
    if mutation == "profile-digest":
        registration["validator"]["toolchainProfile"]["profileDigest"] = (
            "sha256:" + "f" * 64
        )
        assert capability_pack_registry._pack_verification_key(
            registration, "sha256:" + "1" * 64
        ) != original_key
        return

    profile_path = (
        profile_pack_harness.root
        / "core/registries/capability-validator-toolchains.yaml"
    )
    registry = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile = registry["profiles"][0]
    if mutation == "profile-platform":
        profile["platform"]["os"] = "not-" + profile["platform"]["os"]
    elif mutation == "profile-command-digest":
        profile["commands"]["ruby"]["sha256"] = "sha256:" + "2" * 64
    elif mutation == "profile-directory-digest":
        profile["directories"]["javaHome"]["sha256"] = "sha256:" + "3" * 64
    else:
        registry["artifacts"][0]["archiveSha256"] = "sha256:" + "4" * 64
    profile_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    gates = 0
    original_gate = capability_pack_registry._run_candidate_gate

    def observe_gate(*args, **kwargs):
        nonlocal gates
        gates += 1
        return original_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", observe_gate)
    with pytest.raises(
        ValueError, match="toolchain (?:profile|artifact) identity mismatch"
    ):
        get_registered_capability_pack(
            profile_pack_harness.root,
            profile_pack_harness.capability_id,
        )
    assert gates == 0


def test_open_session_rejects_binding_relocation_but_fresh_session_revalidates(
    profile_pack_harness: ProfilePackHarness,
):
    with CapabilityVerificationSession(
        profile_pack_harness.root,
        allowed_capability_ids={profile_pack_harness.capability_id},
    ) as session:
        get_registered_capability_pack(
            profile_pack_harness.root,
            profile_pack_harness.capability_id,
            verification_session=session,
        )
        profile_pack_harness.write_binding(profile_pack_harness.second_root)
        with pytest.raises(
            ValueError,
            match="toolchain binding changed during verification session",
        ):
            get_registered_capability_pack(
                profile_pack_harness.root,
                profile_pack_harness.capability_id,
                verification_session=session,
            )
        with pytest.raises(ValueError, match="failed"):
            get_registered_capability_pack(
                profile_pack_harness.root,
                profile_pack_harness.capability_id,
                verification_session=session,
            )
    with CapabilityVerificationSession(
        profile_pack_harness.root,
        allowed_capability_ids={profile_pack_harness.capability_id},
    ) as fresh:
        get_registered_capability_pack(
            profile_pack_harness.root,
            profile_pack_harness.capability_id,
            verification_session=fresh,
        )
        assert fresh.stats.full_candidate_gate_count == 1
        assert fresh.stats.toolchain_directory_digest_count == 6


def test_new_session_remeasures_mutated_registered_toolchain(
    pack_harness: PackHarness,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    registration = pack_harness.registrations[0]
    toolchain_root = tmp_path / "toolchain"
    trusted_home = toolchain_root / "home"
    java_home = toolchain_root / "java-home"
    maven_home = trusted_home / ".m2/wrapper/dists/apache-maven/fixture"
    repository = trusted_home / ".m2/repository"
    trusted_bin = toolchain_root / "bin"
    for directory in (java_home / "bin", maven_home / "bin", repository, trusted_bin):
        directory.mkdir(parents=True, exist_ok=True)
    bash_bytes = Path("/bin/bash").read_bytes()
    commands = {
        "ruby": trusted_bin / "ruby",
        "rg": trusted_bin / "rg",
        "java": java_home / "bin/java",
        "javac": java_home / "bin/javac",
        "mvn": maven_home / "bin/mvn",
    }
    for path in commands.values():
        path.write_bytes(bash_bytes)
        path.chmod(0o555)
    for root in (java_home, maven_home, repository):
        for path in sorted(root.rglob("*"), reverse=True):
            path.chmod(0o555 if path.is_dir() else 0o444)
        root.chmod(0o555)
    toolchain: dict[str, dict[str, str]] = {
        name: {
            "absolutePath": str(path),
            "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for name, path in commands.items()
    }
    for name, path in {
        "javaHome": java_home,
        "mavenHome": maven_home,
        "mavenRepository": repository,
    }.items():
        toolchain[name] = {
            "absolutePath": str(path),
            "sha256": capability_pack_registry._directory_identity_digest(path),
        }
    registration["validator"]["environmentContract"] = (
        "REGISTERED_TOOLCHAIN_OFFLINE_CACHE"
    )
    registration["validator"]["toolchain"] = toolchain
    pack_harness.write()
    real_gate = capability_pack_registry._run_candidate_gate
    gates = 0

    def counted_gate(*args, **kwargs):
        nonlocal gates
        gates += 1
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", counted_gate)
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as first:
        get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=first,
        )
        first_stats = first.stats
    commands["mvn"].chmod(0o755)
    commands["mvn"].write_bytes(b"mutated toolchain")
    commands["mvn"].chmod(0o555)
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as second:
        with pytest.raises(ValueError, match="toolchain identity mismatch"):
            get_registered_capability_pack(
                pack_harness.root,
                pack_harness.capability_id,
                verification_session=second,
            )
    assert first_stats.full_candidate_gate_count == 1
    assert first_stats.isolated_checkout_count == 1
    assert first_stats.toolchain_directory_digest_count == 6
    assert gates == 1
