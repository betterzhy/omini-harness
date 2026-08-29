from __future__ import annotations

import copy
import json
import os
import platform
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from evolution_harness.hashing import canonical_json_bytes, sha256_bytes
from evolution_harness.schema import SchemaStore, SchemaValidationError
from evolution_harness.toolchain_profile import (
    ToolchainBinding,
    binding_path,
    directory_identity_digest,
    load_toolchain_binding,
    load_toolchain_profile,
    profile_digest,
    verify_profile_toolchain,
)


ROOT = Path(__file__).parents[1]
REGISTRY_SCHEMA = "core/schemas/capability-validator-toolchain-registry.schema.json"
BINDING_SCHEMA = "core/schemas/capability-validator-toolchain-binding.schema.json"
REGISTRATION_SCHEMA = "core/schemas/capability-pack-registration.schema.json"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
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
    )
    return completed.stdout.strip()


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return copy.deepcopy(value)


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() or os.access(path, os.X_OK) else 0o444)
    root.chmod(0o555)


@dataclass
class ProfileHarness:
    root: Path
    profile_id: str
    first_root: Path
    second_root: Path
    profile_digest: str

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
                    toolchain_root / "home/.m2/wrapper/dists/apache-maven/fixture"
                ),
                "mavenRepository": str(toolchain_root / "home/.m2/repository"),
            },
        }

    def write_binding(self, toolchain_root: Path) -> None:
        path = binding_path(self.root, self.profile_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.chmod(0o644)
        path.write_text(
            json.dumps(self.binding_record(toolchain_root)),
            encoding="utf-8",
        )
        path.chmod(0o444)

    def load_profile(self):
        return load_toolchain_profile(self.root, self.profile_id, self.profile_digest)

    def binding(self, toolchain_root: Path) -> ToolchainBinding:
        self.write_binding(toolchain_root)
        return load_toolchain_binding(self.root, self.profile_id)

    def mutated(self, mutation: str):
        profile = _thaw(self.load_profile())
        binding = self.binding(self.first_root)
        commands = dict(binding.command_paths)
        directories = dict(binding.directory_paths)

        if mutation == "relative-path":
            commands["rg"] = Path("bin/rg")
        elif mutation == "symlink":
            link = self.root / "symlink-rg"
            link.symlink_to(commands["rg"])
            commands["rg"] = link
        elif mutation == "wrong-basename":
            commands["rg"] = self.first_root / "bin/not-rg"
        elif mutation == "writable-command":
            commands["rg"].chmod(0o755)
        elif mutation == "wrong-command-digest":
            profile["commands"]["rg"]["sha256"] = "sha256:" + "0" * 64
        elif mutation == "wrong-directory-digest":
            profile["directories"]["javaHome"]["sha256"] = "sha256:" + "0" * 64
        elif mutation == "managed-root-escape":
            outside = self.root / "outside/rg"
            outside.parent.mkdir()
            outside.write_bytes(commands["rg"].read_bytes())
            outside.chmod(0o555)
            commands["rg"] = outside
        elif mutation == "wrong-platform":
            profile["platform"]["os"] = "not-" + platform.system().lower()
        elif mutation == "java-relationship":
            commands["java"] = self.first_root / "detached/bin/java"
        elif mutation == "maven-relationship":
            commands["mvn"] = self.first_root / "detached/bin/mvn"
        elif mutation == "repository-layout":
            directories["mavenRepository"] = self.first_root / "bad/repository"
        else:
            raise AssertionError(f"unknown mutation: {mutation}")

        return profile, ToolchainBinding(
            profile_id=binding.profile_id,
            command_paths=tuple(commands.items()),
            directory_paths=tuple(directories.items()),
            witness_digest=binding.witness_digest,
        )


@pytest.fixture
def profile_harness(tmp_path: Path) -> ProfileHarness:
    root = tmp_path / "harness"
    root.mkdir()
    _git(root, "init", "-q")
    schema_root = root / "core/schemas"
    schema_root.mkdir(parents=True)
    for name in (
        "capability-validator-toolchain-registry.schema.json",
        "capability-validator-toolchain-binding.schema.json",
    ):
        shutil.copy2(ROOT / "core/schemas" / name, schema_root / name)

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
        "detached/bin/java",
        "detached/bin/mvn",
    ):
        path = first_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(executable)
        path.chmod(0o555)
    (first_root / "home/.m2/wrapper/dists/apache-maven/fixture/lib").mkdir()
    (first_root / "home/.m2/wrapper/dists/apache-maven/fixture/lib/core.jar").write_bytes(
        b"maven-core"
    )
    repository = first_root / "home/.m2/repository"
    (repository / "org/example/plugin/1.0").mkdir(parents=True)
    (repository / "org/example/plugin/1.0/plugin.jar").write_bytes(b"plugin")
    (first_root / "bad").mkdir()
    shutil.copytree(repository, first_root / "bad/repository")
    shutil.copy2(first_root / "bin/rg", first_root / "bin/not-rg")
    shutil.copytree(first_root, second_root)
    _make_read_only(first_root)
    _make_read_only(second_root)

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
                "bindingPolicy": "HARNESS_MANAGED_CACHE",
            },
            "mavenRepository": {
                "artifactId": "artifact:maven-repository:test",
                "sha256": directory_identity_digest(first_root / "home/.m2/repository"),
                "bindingPolicy": "HARNESS_MANAGED_CACHE",
            },
        },
        "relationships": {
            "javaHomeCommands": ["java", "javac"],
            "mavenHomeCommand": "mvn",
            "mavenRepositoryLayout": "DOT_M2_REPOSITORY",
        },
    }
    registry = {
        "schemaVersion": "capability-validator-toolchain-registry/v1",
        "artifacts": [artifact],
        "profiles": [profile],
    }
    registry_path = root / "core/registries/capability-validator-toolchains.yaml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    return ProfileHarness(
        root=root,
        profile_id=profile_id,
        first_root=first_root,
        second_root=second_root,
        profile_digest=profile_digest(profile),
    )


def _profile_registry() -> dict[str, Any]:
    return {
        "schemaVersion": "capability-validator-toolchain-registry/v1",
        "artifacts": [
            {
                "artifactId": "artifact:ripgrep:15.2.0:darwin-arm64",
                "kind": "OFFICIAL_RELEASE_ARCHIVE",
                "platform": {"os": "darwin", "architecture": "arm64"},
                "sourceUri": "https://github.com/BurntSushi/ripgrep/releases/download/15.2.0/ripgrep-15.2.0-aarch64-apple-darwin.tar.gz",
                "archiveFormat": "TAR_GZ",
                "archiveSha256": DIGEST_B,
                "extractedRoot": "ripgrep-15.2.0-aarch64-apple-darwin",
            }
        ],
        "profiles": [
            {
                "schemaVersion": "capability-validator-toolchain-profile/v1",
                "profileId": "toolchain-profile:test:darwin-arm64:v1",
                "environmentAdapter": "JAVA_MAVEN_OFFLINE_V1",
                "platform": {"os": "darwin", "architecture": "arm64"},
                "commands": {
                    name: {
                        "artifactId": f"artifact:{name}:fixture",
                        "fileName": name,
                        "sha256": DIGEST_A,
                        "bindingPolicy": "HOST_ATTESTED",
                    }
                    for name in ("ruby", "rg", "java", "javac", "mvn")
                },
                "directories": {
                    name: {
                        "artifactId": f"artifact:{name}:fixture",
                        "sha256": DIGEST_A,
                        "bindingPolicy": "HOST_ATTESTED",
                    }
                    for name in ("javaHome", "mavenHome", "mavenRepository")
                },
                "relationships": {
                    "javaHomeCommands": ["java", "javac"],
                    "mavenHomeCommand": "mvn",
                    "mavenRepositoryLayout": "DOT_M2_REPOSITORY",
                },
            }
        ],
    }


def _host_binding() -> dict[str, Any]:
    return {
        "schemaVersion": "capability-validator-toolchain-binding/v1",
        "profileId": "toolchain-profile:test:darwin-arm64:v1",
        "commands": {
            "ruby": "/opt/toolchain/bin/ruby",
            "rg": "/opt/toolchain/bin/rg",
            "java": "/opt/toolchain/java/bin/java",
            "javac": "/opt/toolchain/java/bin/javac",
            "mvn": "/opt/toolchain/maven/bin/mvn",
        },
        "directories": {
            "javaHome": "/opt/toolchain/java",
            "mavenHome": "/opt/toolchain/maven",
            "mavenRepository": "/opt/toolchain/home/.m2/repository",
        },
    }


def _registration() -> dict[str, Any]:
    toolchain = {
        name: {"absolutePath": f"/opt/toolchain/bin/{name}", "sha256": DIGEST_A}
        for name in ("ruby", "rg", "java", "javac", "mvn")
    }
    toolchain.update(
        {
            name: {"absolutePath": f"/opt/toolchain/{name}", "sha256": DIGEST_A}
            for name in ("javaHome", "mavenHome", "mavenRepository")
        }
    )
    return {
        "schemaVersion": "capability-pack-registration/v1",
        "registrationId": "pack:test",
        "capabilityId": "framework:test:test",
        "packVersion": "1.0.0",
        "status": "ACTIVE",
        "distributionStatus": "LOCAL_ONLY",
        "source": {
            "kind": "LOCAL_GIT",
            "repositoryId": "test",
            "repositoryPath": "/tmp/test-pack",
            "commit": "1" * 40,
            "tree": "2" * 40,
        },
        "resolvedContentDigest": DIGEST_A,
        "validator": {
            "kind": "FIXED_CANDIDATE_GATE",
            "relativePath": "scripts/verify-capability-pack",
            "sha256": DIGEST_B,
            "argumentsContract": "CANDIDATE_COMMIT_TREE",
            "environmentContract": "REGISTERED_TOOLCHAIN_OFFLINE_CACHE",
            "toolchain": toolchain,
        },
    }


def _profile_registration() -> dict[str, Any]:
    registration = _registration()
    registration["validator"]["environmentContract"] = "MANAGED_TOOLCHAIN_PROFILE"
    del registration["validator"]["toolchain"]
    registration["validator"]["toolchainProfile"] = {
        "profileId": "toolchain-profile:test:darwin-arm64:v1",
        "profileDigest": DIGEST_A,
    }
    return registration


def test_toolchain_registry_schema_accepts_locator_free_profile():
    SchemaStore(ROOT).validate(REGISTRY_SCHEMA, _profile_registry())


def test_toolchain_registry_schema_accepts_non_java_relationships():
    registry = {
        "schemaVersion": "capability-validator-toolchain-registry/v1",
        "artifacts": [],
        "profiles": [
            {
                "schemaVersion": "capability-validator-toolchain-profile/v1",
                "profileId": "toolchain-profile:ruby-offline:darwin-arm64:v1",
                "environmentAdapter": "RUBY_OFFLINE_V1",
                "platform": {"os": "darwin", "architecture": "arm64"},
                "commands": {
                    "ruby": {
                        "artifactId": "artifact:ruby:fixture",
                        "fileName": "ruby",
                        "sha256": DIGEST_A,
                        "bindingPolicy": "HOST_ATTESTED",
                    }
                },
                "directories": {
                    "runtimeHome": {
                        "artifactId": "artifact:ruby:fixture",
                        "sha256": DIGEST_B,
                        "bindingPolicy": "HOST_ATTESTED",
                    }
                },
                "relationships": {"runtimeHomeCommand": "ruby"},
            }
        ],
    }

    SchemaStore(ROOT).validate(REGISTRY_SCHEMA, registry)


@pytest.mark.parametrize(
    ("section", "name"),
    [("commands", "rg"), ("directories", "javaHome")],
)
def test_toolchain_profile_schema_rejects_host_locator(section: str, name: str):
    registry = _profile_registry()
    registry["profiles"][0][section][name]["absolutePath"] = "/Applications/ChatGPT.app/Contents/Resources/rg"

    with pytest.raises(SchemaValidationError, match="absolutePath"):
        SchemaStore(ROOT).validate(REGISTRY_SCHEMA, registry)


def test_toolchain_profile_directory_requires_binding_policy():
    registry = _profile_registry()
    del registry["profiles"][0]["directories"]["javaHome"]["bindingPolicy"]

    with pytest.raises(SchemaValidationError, match="bindingPolicy"):
        SchemaStore(ROOT).validate(REGISTRY_SCHEMA, registry)


@pytest.mark.parametrize("section", ["commands", "directories"])
def test_toolchain_profile_rejects_unsafe_logical_name(section: str):
    registry = _profile_registry()
    identity = registry["profiles"][0][section].pop(next(iter(registry["profiles"][0][section])))
    registry["profiles"][0][section]["../host-path"] = identity

    with pytest.raises(SchemaValidationError, match="host-path"):
        SchemaStore(ROOT).validate(REGISTRY_SCHEMA, registry)


def test_managed_store_command_requires_artifact_digest():
    registry = _profile_registry()
    registry["profiles"][0]["commands"]["rg"]["bindingPolicy"] = "HARNESS_MANAGED_STORE"

    with pytest.raises(SchemaValidationError, match="artifactDigest"):
        SchemaStore(ROOT).validate(REGISTRY_SCHEMA, registry)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda profile: profile["commands"].pop("ruby"),
        lambda profile: profile["commands"].update(
            {
                "python": {
                    "artifactId": "artifact:python:fixture",
                    "fileName": "python",
                    "sha256": DIGEST_A,
                    "bindingPolicy": "HOST_ATTESTED",
                }
            }
        ),
        lambda profile: profile["directories"].pop("mavenRepository"),
    ],
)
def test_java_maven_profile_requires_exact_logical_identities(mutation):
    registry = _profile_registry()
    mutation(registry["profiles"][0])

    with pytest.raises(SchemaValidationError):
        SchemaStore(ROOT).validate(REGISTRY_SCHEMA, registry)


def test_toolchain_binding_schema_accepts_absolute_host_locators():
    SchemaStore(ROOT).validate(BINDING_SCHEMA, _host_binding())


def test_toolchain_binding_schema_rejects_relative_host_locator():
    binding = _host_binding()
    binding["commands"]["rg"] = "bin/rg"

    with pytest.raises(SchemaValidationError, match="bin/rg"):
        SchemaStore(ROOT).validate(BINDING_SCHEMA, binding)


def test_toolchain_artifact_registry_is_valid_and_exact():
    registry = yaml.safe_load(
        (ROOT / "core/registries/capability-validator-toolchains.yaml").read_text(
            encoding="utf-8"
        )
    )
    SchemaStore(ROOT).validate(REGISTRY_SCHEMA, registry)

    assert registry["profiles"] == []
    assert registry["artifacts"] == [
        {
            "artifactId": "artifact:ripgrep:15.2.0:darwin-arm64",
            "kind": "OFFICIAL_RELEASE_ARCHIVE",
            "platform": {"os": "darwin", "architecture": "arm64"},
            "sourceUri": "https://github.com/BurntSushi/ripgrep/releases/download/15.2.0/ripgrep-15.2.0-aarch64-apple-darwin.tar.gz",
            "archiveFormat": "TAR_GZ",
            "archiveSha256": "sha256:3750b2e93f37e0c692657da574d7019a101c0084da05a790c83fd335bad973e4",
            "extractedRoot": "ripgrep-15.2.0-aarch64-apple-darwin",
            "extractedFiles": {
                "rg": "sha256:a326a1fb48074202e9ad41e4cd1e389eeea372c8c6f7d7e80da81176d5d9430e"
            },
            "provenancePolicy": "OFFICIAL_GITHUB_RELEASE_ARCHIVE_SHA256",
        }
    ]
    assert "sha256:" + sha256_bytes(canonical_json_bytes(registry["artifacts"][0])) == (
        "sha256:bfa2614eba25313624c604d16c6c727f3b243e5453b5b261321858f7eee75512"
    )


def test_legacy_registration_requires_toolchain():
    registration = _registration()
    del registration["validator"]["toolchain"]

    with pytest.raises(SchemaValidationError, match="toolchain"):
        SchemaStore(ROOT).validate(REGISTRATION_SCHEMA, registration)


def test_profile_registration_requires_toolchain_profile():
    registration = _profile_registration()
    del registration["validator"]["toolchainProfile"]

    with pytest.raises(SchemaValidationError, match="toolchainProfile"):
        SchemaStore(ROOT).validate(REGISTRATION_SCHEMA, registration)


def test_profile_registration_rejects_legacy_toolchain():
    registration = _profile_registration()
    registration["validator"]["toolchain"] = copy.deepcopy(_registration()["validator"]["toolchain"])

    with pytest.raises(SchemaValidationError, match="toolchain"):
        SchemaStore(ROOT).validate(REGISTRATION_SCHEMA, registration)


@pytest.mark.parametrize(
    "profile_digest",
    ["a" * 64, "sha256:" + "A" * 64, "sha256:" + "a" * 63],
)
def test_profile_registration_requires_canonical_sha256_digest(profile_digest: str):
    registration = _profile_registration()
    registration["validator"]["toolchainProfile"]["profileDigest"] = profile_digest

    with pytest.raises(SchemaValidationError, match="profileDigest"):
        SchemaStore(ROOT).validate(REGISTRATION_SCHEMA, registration)


def test_legacy_and_profile_registrations_are_both_valid():
    store = SchemaStore(ROOT)
    store.validate(REGISTRATION_SCHEMA, _registration())
    store.validate(REGISTRATION_SCHEMA, _profile_registration())


def test_binding_path_uses_git_common_repository_root(tmp_path: Path):
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "Profile Test")
    _git(repository, "config", "user.email", "profile-test@example.invalid")
    (repository / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-qm", "test: profile binding common root")
    worktree = repository / ".worktrees/fixture"
    _git(repository, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")

    actual = binding_path(worktree, "toolchain-profile:test:darwin-arm64:v1")

    assert actual.parent == repository / ".worktrees/.capability-pack-cache/bindings"


def test_profile_digest_excludes_binding_paths(profile_harness: ProfileHarness):
    first = load_toolchain_profile(
        profile_harness.root,
        profile_harness.profile_id,
        profile_harness.profile_digest,
    )
    profile_harness.write_binding(profile_harness.second_root)
    second = load_toolchain_profile(
        profile_harness.root,
        profile_harness.profile_id,
        profile_harness.profile_digest,
    )

    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_binding_relocation_changes_witness_not_verified_profile(
    profile_harness: ProfileHarness,
):
    profile = profile_harness.load_profile()
    first_binding = profile_harness.binding(profile_harness.first_root)
    second_binding = profile_harness.binding(profile_harness.second_root)

    first = verify_profile_toolchain(profile_harness.root, profile, first_binding)
    second = verify_profile_toolchain(profile_harness.root, profile, second_binding)

    assert first.profile_digest == second.profile_digest
    assert first.binding_witness != second.binding_witness
    assert first.command_digests == second.command_digests
    assert tuple((name, digest) for name, _, digest in first.directory_identities) == tuple(
        (name, digest) for name, _, digest in second.directory_identities
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("relative-path", "binding path is unavailable or unsafe"),
        ("symlink", "binding path is unavailable or unsafe"),
        ("wrong-basename", "command basename mismatch"),
        ("writable-command", "command is writable"),
        ("wrong-command-digest", "command identity mismatch"),
        ("wrong-directory-digest", "directory identity mismatch"),
        ("managed-root-escape", "outside Harness managed store"),
        ("wrong-platform", "toolchain profile platform mismatch"),
        ("java-relationship", "Java home identity mismatch"),
        ("maven-relationship", "Maven home identity mismatch"),
        ("repository-layout", "Maven repository identity mismatch"),
    ],
)
def test_profile_binding_fails_closed(
    profile_harness: ProfileHarness, mutation: str, message: str
):
    profile, binding = profile_harness.mutated(mutation)

    with pytest.raises(ValueError, match=message):
        verify_profile_toolchain(profile_harness.root, profile, binding)


def test_profile_binding_does_not_fall_back_to_ambient_path(
    profile_harness: ProfileHarness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    (ambient / "rg").write_bytes((profile_harness.first_root / "bin/rg").read_bytes())
    (ambient / "rg").chmod(0o555)
    monkeypatch.setenv("PATH", str(ambient))
    profile = profile_harness.load_profile()
    binding = profile_harness.binding(profile_harness.first_root)
    commands = tuple(
        (name, path) for name, path in binding.command_paths if name != "rg"
    )
    incomplete = ToolchainBinding(
        profile_id=binding.profile_id,
        command_paths=commands,
        directory_paths=binding.directory_paths,
        witness_digest=binding.witness_digest,
    )

    with pytest.raises(
        ValueError, match="capability pack toolchain binding is incomplete"
    ):
        verify_profile_toolchain(profile_harness.root, profile, incomplete)


def test_profile_verification_rejects_artifact_registry_drift_before_binding(
    profile_harness: ProfileHarness,
):
    registry_path = (
        profile_harness.root
        / "core/registries/capability-validator-toolchains.yaml"
    )
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["artifacts"][0]["archiveSha256"] = "sha256:" + "2" * 64
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="toolchain artifact identity mismatch"):
        load_toolchain_profile(
            profile_harness.root,
            profile_harness.profile_id,
            profile_harness.profile_digest,
        )


def test_reordered_profile_map_keeps_canonical_command_resolution(
    profile_harness: ProfileHarness,
):
    canonical = profile_harness.load_profile()
    reordered = _thaw(canonical)
    reordered["commands"] = dict(reversed(tuple(reordered["commands"].items())))
    binding = profile_harness.binding(profile_harness.first_root)

    first = verify_profile_toolchain(profile_harness.root, canonical, binding)
    second = verify_profile_toolchain(profile_harness.root, reordered, binding)

    assert first.profile_digest == second.profile_digest
    assert first.command_paths == second.command_paths
    assert first.command_digests == second.command_digests
    assert first.environment["PATH"] == second.environment["PATH"]


def test_profile_binding_rejects_shadowed_logical_command(
    profile_harness: ProfileHarness,
):
    shadow = profile_harness.first_root / "bin/java"
    shadow.parent.chmod(0o755)
    shadow.write_bytes(
        (profile_harness.first_root / "java/bin/java").read_bytes()
    )
    shadow.chmod(0o555)
    shadow.parent.chmod(0o555)

    with pytest.raises(ValueError, match="effective command resolution mismatch"):
        verify_profile_toolchain(
            profile_harness.root,
            profile_harness.load_profile(),
            profile_harness.binding(profile_harness.first_root),
        )


def test_toolchain_binding_rejects_writable_record(
    profile_harness: ProfileHarness,
):
    profile_harness.write_binding(profile_harness.first_root)
    path = binding_path(profile_harness.root, profile_harness.profile_id)
    path.chmod(0o644)

    with pytest.raises(ValueError, match="toolchain binding is writable"):
        load_toolchain_binding(profile_harness.root, profile_harness.profile_id)
