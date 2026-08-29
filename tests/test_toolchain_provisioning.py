from __future__ import annotations

import hashlib
import io
import os
import platform
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from evolution_harness.hashing import canonical_json_bytes, sha256_bytes
from evolution_harness.toolchain_profile import (
    binding_path,
    directory_identity_digest,
)
from evolution_harness.toolchain_provisioning import (
    plan_toolchain_provision,
    provision_toolchain,
    toolchain_status,
)


ROOT = Path(__file__).parents[1]
EXECUTABLE = b"#!/bin/sh\nexit 0\n"


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["/usr/bin/git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": "/var/empty",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    )


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() or os.access(path, os.X_OK) else 0o444)
    root.chmod(0o555)


def _tar_member(name: str, data: bytes | None = None) -> tuple[tarfile.TarInfo, bytes | None]:
    member = tarfile.TarInfo(name)
    if data is None:
        member.type = tarfile.DIRTYPE
        member.mode = 0o755
        member.size = 0
    else:
        member.type = tarfile.REGTYPE
        member.mode = 0o755
        member.size = len(data)
    return member, data


def _archive_bytes(member_kind: str) -> bytes:
    members = [
        _tar_member("ripgrep-test"),
        _tar_member("ripgrep-test/rg", EXECUTABLE),
    ]
    if member_kind == "parent-traversal":
        members.append(_tar_member("../escape", b"escape"))
    elif member_kind == "absolute-path":
        members.append(_tar_member("/absolute", b"escape"))
    elif member_kind in {"symlink", "hardlink", "fifo"}:
        member = tarfile.TarInfo(f"ripgrep-test/{member_kind}")
        member.type = {
            "symlink": tarfile.SYMTYPE,
            "hardlink": tarfile.LNKTYPE,
            "fifo": tarfile.FIFOTYPE,
        }[member_kind]
        member.linkname = "rg"
        members.append((member, None))
    elif member_kind == "duplicate-normalized":
        members.extend(
            [
                _tar_member("ripgrep-test/caf\N{LATIN SMALL LETTER E WITH ACUTE}", b"one"),
                _tar_member("ripgrep-test/cafe\N{COMBINING ACUTE ACCENT}", b"two"),
            ]
        )
    elif member_kind != "safe":
        raise AssertionError(f"unknown archive kind: {member_kind}")

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for member, data in members:
            archive.addfile(member, io.BytesIO(data) if data is not None else None)
    return buffer.getvalue()


@dataclass
class ProvisionHarness:
    root: Path
    profile_id: str
    artifact_id: str
    explicit_bindings: dict[str, Path]
    archive_path: Path

    @property
    def binding_path(self) -> Path:
        return binding_path(self.root, self.profile_id)

    @property
    def registry_path(self) -> Path:
        return self.root / "core/registries/capability-validator-toolchains.yaml"

    @property
    def published_root(self) -> Path:
        registry = yaml.safe_load(self.registry_path.read_text(encoding="utf-8"))
        digest = registry["artifacts"][0]["archiveSha256"].removeprefix("sha256:")
        artifact_key = hashlib.sha256(self.artifact_id.encode("utf-8")).hexdigest()
        return (
            self.root
            / ".worktrees/.capability-pack-cache/store"
            / artifact_key
            / digest
        )

    def archive(self, member_kind: str = "safe") -> Path:
        data = _archive_bytes(member_kind)
        self.archive_path.write_bytes(data)
        self._update_registry(archive_digest="sha256:" + sha256_bytes(data))
        return self.archive_path

    def _update_registry(
        self,
        *,
        archive_digest: str | None = None,
        extracted_digest: str | None = None,
    ) -> None:
        registry = yaml.safe_load(self.registry_path.read_text(encoding="utf-8"))
        artifact = registry["artifacts"][0]
        profile = registry["profiles"][0]
        if archive_digest is not None:
            artifact["archiveSha256"] = archive_digest
        if extracted_digest is not None:
            artifact["extractedFiles"]["rg"] = extracted_digest
            profile["commands"]["rg"]["sha256"] = extracted_digest
        profile["commands"]["rg"]["artifactDigest"] = (
            "sha256:" + sha256_bytes(canonical_json_bytes(artifact))
        )
        self.registry_path.write_text(
            yaml.safe_dump(registry, sort_keys=False), encoding="utf-8"
        )


def make_provision_harness(tmp_path: Path) -> ProvisionHarness:
    root = tmp_path / "harness"
    root.mkdir()
    _git(root, "init", "-q")
    schemas = root / "core/schemas"
    schemas.mkdir(parents=True)
    for name in (
        "capability-validator-toolchain-registry.schema.json",
        "capability-validator-toolchain-binding.schema.json",
    ):
        shutil.copy2(ROOT / "core/schemas" / name, schemas / name)

    ruby = tmp_path / "host/bin/ruby"
    java_home = tmp_path / "host/java"
    for path in (ruby, java_home / "bin/java", java_home / "bin/javac"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(EXECUTABLE)
        path.chmod(0o555)

    cache = root / ".worktrees/.capability-pack-cache"
    home = cache / "host/home"
    maven_home = home / ".m2/wrapper/dists/apache-maven/fixture"
    mvn = maven_home / "bin/mvn"
    mvn.parent.mkdir(parents=True)
    mvn.write_bytes(EXECUTABLE)
    mvn.chmod(0o555)
    (maven_home / "lib").mkdir()
    (maven_home / "lib/core.jar").write_bytes(b"maven-core")
    repository = home / ".m2/repository"
    (repository / "org/example/plugin/1.0").mkdir(parents=True)
    (repository / "org/example/plugin/1.0/plugin.jar").write_bytes(b"plugin")
    _make_read_only(java_home)
    _make_read_only(maven_home)
    _make_read_only(repository)

    archive_path = tmp_path / "ripgrep.tar.gz"
    archive_data = _archive_bytes("safe")
    archive_path.write_bytes(archive_data)
    command_digest = "sha256:" + sha256_bytes(EXECUTABLE)
    artifact_id = "artifact:ripgrep:test:darwin-arm64"
    artifact = {
        "artifactId": artifact_id,
        "kind": "OFFICIAL_RELEASE_ARCHIVE",
        "platform": {
            "os": platform.system().lower(),
            "architecture": platform.machine().lower(),
        },
        "sourceUri": "https://example.invalid/ripgrep.tar.gz",
        "archiveFormat": "TAR_GZ",
        "archiveSha256": "sha256:" + sha256_bytes(archive_data),
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
            "ruby": {
                "artifactId": "artifact:ruby:test",
                "fileName": "ruby",
                "sha256": command_digest,
                "bindingPolicy": "HOST_ATTESTED",
            },
            "rg": {
                "artifactId": artifact_id,
                "artifactDigest": artifact_digest,
                "fileName": "rg",
                "sha256": command_digest,
                "bindingPolicy": "HARNESS_MANAGED_STORE",
            },
            "java": {
                "artifactId": "artifact:java:test",
                "fileName": "java",
                "sha256": command_digest,
                "bindingPolicy": "HOST_ATTESTED",
            },
            "javac": {
                "artifactId": "artifact:java:test",
                "fileName": "javac",
                "sha256": command_digest,
                "bindingPolicy": "HOST_ATTESTED",
            },
            "mvn": {
                "artifactId": "artifact:maven:test",
                "fileName": "mvn",
                "sha256": command_digest,
                "bindingPolicy": "HARNESS_MANAGED_CACHE",
            },
        },
        "directories": {
            "javaHome": {
                "artifactId": "artifact:java:test",
                "sha256": directory_identity_digest(java_home),
                "bindingPolicy": "HOST_ATTESTED",
            },
            "mavenHome": {
                "artifactId": "artifact:maven:test",
                "sha256": directory_identity_digest(maven_home),
                "bindingPolicy": "HARNESS_MANAGED_CACHE",
            },
            "mavenRepository": {
                "artifactId": "artifact:maven-repository:test",
                "sha256": directory_identity_digest(repository),
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
    registry_path.write_text(
        yaml.safe_dump(registry, sort_keys=False), encoding="utf-8"
    )
    return ProvisionHarness(
        root=root,
        profile_id=profile_id,
        artifact_id=artifact_id,
        explicit_bindings={
            "ruby": ruby,
            "java": java_home / "bin/java",
            "javac": java_home / "bin/javac",
            "mvn": mvn,
            "javaHome": java_home,
            "mavenHome": maven_home,
            "mavenRepository": repository,
        },
        archive_path=archive_path,
    )


@pytest.fixture
def provision_harness(tmp_path: Path) -> ProvisionHarness:
    return make_provision_harness(tmp_path)


@pytest.mark.parametrize(
    ("member_kind", "message"),
    [
        ("parent-traversal", "archive member path is unsafe"),
        ("absolute-path", "archive member path is unsafe"),
        ("symlink", "archive contains link or special file"),
        ("hardlink", "archive contains link or special file"),
        ("fifo", "archive contains link or special file"),
        ("duplicate-normalized", "archive member path is duplicated"),
    ],
)
def test_provision_rejects_unsafe_archive(
    provision_harness: ProvisionHarness,
    member_kind: str,
    message: str,
):
    archive = provision_harness.archive(member_kind)

    with pytest.raises(ValueError, match=message):
        provision_toolchain(
            provision_harness.root,
            provision_harness.profile_id,
            provision_harness.explicit_bindings,
            archive,
        )

    assert not provision_harness.binding_path.exists()
    assert not provision_harness.published_root.exists()


def test_provision_rejects_wrong_archive_sha256(
    provision_harness: ProvisionHarness,
):
    archive = provision_harness.archive()
    archive.write_bytes(archive.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="toolchain archive identity mismatch"):
        provision_toolchain(
            provision_harness.root,
            provision_harness.profile_id,
            provision_harness.explicit_bindings,
            archive,
        )

    assert not provision_harness.binding_path.exists()
    assert not provision_harness.published_root.exists()


def test_provision_rejects_wrong_extracted_rg_sha256(
    provision_harness: ProvisionHarness,
):
    archive = provision_harness.archive()
    provision_harness._update_registry(extracted_digest="sha256:" + "0" * 64)

    with pytest.raises(ValueError, match="extracted command identity mismatch"):
        provision_toolchain(
            provision_harness.root,
            provision_harness.profile_id,
            provision_harness.explicit_bindings,
            archive,
        )

    assert not provision_harness.binding_path.exists()
    assert not provision_harness.published_root.exists()


def test_interrupted_store_replace_publishes_neither_store_nor_binding(
    provision_harness: ProvisionHarness,
    monkeypatch: pytest.MonkeyPatch,
):
    real_replace = os.replace

    def interrupted(source: str | Path, target: str | Path) -> None:
        if Path(target) == provision_harness.published_root:
            raise OSError("interrupted store publication")
        real_replace(source, target)

    monkeypatch.setattr("evolution_harness.toolchain_provisioning.os.replace", interrupted)

    with pytest.raises(OSError, match="interrupted store publication"):
        provision_toolchain(
            provision_harness.root,
            provision_harness.profile_id,
            provision_harness.explicit_bindings,
            provision_harness.archive(),
        )

    assert not provision_harness.binding_path.exists()
    assert not provision_harness.published_root.exists()


def test_binding_write_failure_leaves_only_immutable_unreferenced_store(
    provision_harness: ProvisionHarness,
    monkeypatch: pytest.MonkeyPatch,
):
    real_replace = os.replace

    def interrupted(source: str | Path, target: str | Path) -> None:
        if Path(target) == provision_harness.binding_path:
            raise OSError("interrupted binding publication")
        real_replace(source, target)

    monkeypatch.setattr("evolution_harness.toolchain_provisioning.os.replace", interrupted)

    with pytest.raises(OSError, match="interrupted binding publication"):
        provision_toolchain(
            provision_harness.root,
            provision_harness.profile_id,
            provision_harness.explicit_bindings,
            provision_harness.archive(),
        )

    assert not provision_harness.binding_path.exists()
    assert provision_harness.published_root.is_dir()
    assert provision_harness.published_root.stat().st_mode & 0o222 == 0
    assert all(path.stat().st_mode & 0o222 == 0 for path in provision_harness.published_root.rglob("*"))


def test_same_content_reprovision_reuses_store_without_mutation(
    provision_harness: ProvisionHarness,
):
    archive = provision_harness.archive()
    first = provision_toolchain(
        provision_harness.root,
        provision_harness.profile_id,
        provision_harness.explicit_bindings,
        archive,
    )
    store_identity = (
        provision_harness.published_root.stat().st_ino,
        provision_harness.published_root.stat().st_mtime_ns,
        directory_identity_digest(provision_harness.published_root),
    )

    second = provision_toolchain(
        provision_harness.root,
        provision_harness.profile_id,
        provision_harness.explicit_bindings,
        archive,
    )

    assert second == first
    assert (
        provision_harness.published_root.stat().st_ino,
        provision_harness.published_root.stat().st_mtime_ns,
        directory_identity_digest(provision_harness.published_root),
    ) == store_identity


def test_existing_content_address_conflict_fails_closed(
    provision_harness: ProvisionHarness,
):
    provision_harness.archive()
    target = provision_harness.published_root
    target.mkdir(parents=True)
    (target / "conflict").write_bytes(b"different")
    _make_read_only(target)

    with pytest.raises(ValueError, match="managed store identity conflict"):
        provision_toolchain(
            provision_harness.root,
            provision_harness.profile_id,
            provision_harness.explicit_bindings,
            provision_harness.archive_path,
        )

    assert not provision_harness.binding_path.exists()


def test_dry_run_is_read_only_and_reports_fixed_plan(
    provision_harness: ProvisionHarness,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "evolution_harness.toolchain_provisioning.urlopen",
        lambda *_args, **_kwargs: pytest.fail("network used"),
    )

    result = plan_toolchain_provision(
        provision_harness.root,
        provision_harness.profile_id,
        provision_harness.explicit_bindings,
        None,
    )

    assert result["apply"] is False
    assert result["profileId"] == provision_harness.profile_id
    assert result["source"] == "download"
    assert result["command"] == (
        "harness toolchain provision --profile "
        f"{provision_harness.profile_id} --apply"
    )
    assert not provision_harness.binding_path.exists()
    assert not provision_harness.published_root.exists()


def test_missing_binding_status_is_offline_and_actionable(
    provision_harness: ProvisionHarness,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "evolution_harness.toolchain_provisioning.urlopen",
        lambda *_args, **_kwargs: pytest.fail("network used"),
    )

    result = toolchain_status(
        provision_harness.root, provision_harness.profile_id
    )

    assert result["status"] == "MISSING"
    assert result["artifactId"] == provision_harness.artifact_id
    assert result["platform"] == {
        "os": platform.system().lower(),
        "architecture": platform.machine().lower(),
    }
    assert result["message"] == (
        "toolchain binding is unavailable; provision explicitly with: "
        "harness toolchain provision --profile "
        f"{provision_harness.profile_id} --apply"
    )


def test_candidate_validation_missing_binding_is_offline_and_actionable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from evolution_harness.capability_pack_registry import (
        get_registered_capability_pack,
    )
    from test_capability_pack_registry import _managed_profile_harness

    root, registration = _managed_profile_harness(tmp_path)
    profile_id = registration["validator"]["toolchainProfile"]["profileId"]
    binding_path(root, profile_id).unlink()
    monkeypatch.setattr(
        "evolution_harness.toolchain_provisioning.urlopen",
        lambda *_args, **_kwargs: pytest.fail("network used"),
    )

    with pytest.raises(ValueError) as failure:
        get_registered_capability_pack(root, registration["capabilityId"])

    message = str(failure.value)
    assert f"profile={profile_id}" in message
    assert "managedArtifacts=artifact:ripgrep:test:darwin-arm64" in message
    assert (
        f"platform={platform.system().lower()}/{platform.machine().lower()}" in message
    )
    assert (
        "harness toolchain provision --profile " f"{profile_id} --apply"
    ) in message


def test_apply_without_archive_uses_fixed_download_with_timeout(
    provision_harness: ProvisionHarness,
    monkeypatch: pytest.MonkeyPatch,
):
    archive = provision_harness.archive().read_bytes()
    calls: list[tuple[str, int]] = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            self.close()

    def fixed_download(uri: str, *, timeout: int):
        calls.append((uri, timeout))
        return Response(archive)

    monkeypatch.setattr(
        "evolution_harness.toolchain_provisioning.urlopen", fixed_download
    )

    result = provision_toolchain(
        provision_harness.root,
        provision_harness.profile_id,
        provision_harness.explicit_bindings,
        None,
    )

    assert result["apply"] is True
    assert calls == [("https://example.invalid/ripgrep.tar.gz", 30)]
    assert toolchain_status(provision_harness.root, provision_harness.profile_id)[
        "status"
    ] == "READY"


def test_download_response_over_64_mib_is_rejected(
    provision_harness: ProvisionHarness,
    monkeypatch: pytest.MonkeyPatch,
):
    class OversizedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            assert size == 64 * 1024 * 1024 + 1
            return b"x" * size

    monkeypatch.setattr(
        "evolution_harness.toolchain_provisioning.urlopen",
        lambda *_args, **_kwargs: OversizedResponse(),
    )

    with pytest.raises(ValueError, match="download exceeds 64 MiB"):
        provision_toolchain(
            provision_harness.root,
            provision_harness.profile_id,
            provision_harness.explicit_bindings,
            None,
        )

    assert not provision_harness.binding_path.exists()
    assert not provision_harness.published_root.exists()
