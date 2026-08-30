from __future__ import annotations

import hashlib
import json
import os
import platform
import signal
import shlex
import shutil
import stat
import subprocess
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from evolution_harness import capability_pack_registry
from evolution_harness.capability_pack_registry import (
    _registration_fingerprint,
    build_capability_pack_registry,
    get_registered_capability_pack,
    load_capability_pack_registrations,
)
from evolution_harness.hashing import canonical_json_bytes, sha256_bytes
from evolution_harness.toolchain_profile import (
    binding_path,
    directory_identity_digest,
    profile_digest,
)


CAPABILITY_ID = "workflow:web-high-fidelity:reference-driven-visual-fidelity"
REGISTRATION_ID = "pack:web-high-fidelity"
FIXTURE_CONTENT_DIGEST = "sha256:42e88d096cd91ade629f1bb47474f24a7730c76c43cf250ae0bc549c30654cd7"
JAVA_CAPABILITY_ID = "framework:java:java-engineering-standard"
JAVA_REGISTRATION_ID = "pack:java-engineering-standard"
JAVA_SOURCE_COMMIT = "01d0e7d15ef9f6aa7814b0b001fa0b7c2c30e882"
JAVA_SOURCE_TREE = "4bfc51d75c9e01e585db4cc073f952043ea01393"


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
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return completed.stdout.strip()


def _manifest() -> dict[str, Any]:
    return {
        "schemaVersion": "capability-pack/v1",
        "projectPackName": "web-high-fidelity",
        "skillName": "web-high-fidelity",
        "displayName": "Reference-Driven Web Visual Fidelity",
        "capabilityId": CAPABILITY_ID,
        "version": "2.0.0",
        "contentDigestContract": "capability-pack-content/v1",
        "contentRoots": ["docs", "skills"],
        "excludedContentRoots": ["docs/history"],
        "skillPath": "skills/web-high-fidelity/SKILL.md",
        "validator": {
            "kind": "FIXED_CANDIDATE_GATE",
            "path": "scripts/verify-capability-pack",
            "argumentsContract": "CANDIDATE_COMMIT_TREE",
        },
    }


def _write_valid_pack(source: Path) -> None:
    (source / "docs/history").mkdir(parents=True)
    (source / "skills/web-high-fidelity").mkdir(parents=True)
    (source / "scripts").mkdir()
    (source / "capability-pack.yaml").write_text(
        yaml.safe_dump(_manifest(), sort_keys=False), encoding="utf-8"
    )
    (source / "VERSION").write_text("2.0.0\n", encoding="utf-8")
    (source / "docs/active.txt").write_text("active content\n", encoding="utf-8")
    (source / "docs/history/ignored.txt").write_text("excluded content\n", encoding="utf-8")
    (source / "skills/web-high-fidelity/SKILL.md").write_text(
        "# Test Skill\n", encoding="utf-8"
    )
    validator = source / "scripts/verify-capability-pack"
    validator.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "[ \"$#\" -eq 2 ]\n"
        "[ \"$(git -C \"${0%/*}/..\" rev-parse HEAD)\" = \"$1\" ]\n"
        "[ \"$(git -C \"${0%/*}/..\" rev-parse 'HEAD^{tree}')\" = \"$2\" ]\n"
        "[ -z \"$(git -C \"${0%/*}/..\" status --porcelain=v1 --untracked-files=all)\" ]\n",
        encoding="utf-8",
    )
    validator.chmod(0o755)


def _pack_fixture(tmp_path: Path) -> tuple[Path, str, str]:
    source = tmp_path / "pack"
    source.mkdir()
    _write_valid_pack(source)
    _git(source, "init", "-q")
    _git(source, "config", "user.name", "Pack Test")
    _git(source, "config", "user.email", "pack-test@example.invalid")
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "test: pack fixture")
    commit = _git(source, "rev-parse", "HEAD")
    tree = _git(source, "rev-parse", "HEAD^{tree}")
    return source, commit, tree


def _selected_paths(
    source: Path,
    manifest: dict[str, Any],
    *,
    include_tracked_manifest: bool = True,
) -> list[str]:
    tracked = _git(source, "ls-files", "-z").split("\0")
    excluded = tuple(manifest["excludedContentRoots"])
    selected = {"VERSION"}
    if include_tracked_manifest:
        selected.add("capability-pack.yaml")
    for relative in tracked:
        if not relative:
            continue
        if any(relative == root or relative.startswith(root + "/") for root in excluded):
            continue
        if any(
            relative == root or relative.startswith(root + "/")
            for root in manifest["contentRoots"]
        ):
            selected.add(relative)
    return sorted(selected, key=lambda value: value.encode("utf-8"))


def _expected_content_digest(
    source: Path,
    manifest: dict[str, Any],
    *,
    include_tracked_manifest: bool = True,
) -> str:
    digest = hashlib.sha256()
    for relative in _selected_paths(
        source,
        manifest,
        include_tracked_manifest=include_tracked_manifest,
    ):
        stage = _git(source, "ls-files", "--stage", "--", relative).split()
        mode = stage[0].encode("ascii")
        blob = (source / relative).read_bytes()
        fields = (
            relative.encode("utf-8"),
            mode,
            str(len(blob)).encode("ascii"),
            blob,
        )
        for field in fields:
            digest.update(len(field).to_bytes(8, byteorder="big"))
            digest.update(field)
    return "sha256:" + digest.hexdigest()


def _registration(source: Path, commit: str, tree: str) -> dict[str, Any]:
    manifest = yaml.safe_load((source / "capability-pack.yaml").read_text(encoding="utf-8"))
    return {
        "schemaVersion": "capability-pack-registration/v1",
        "registrationId": REGISTRATION_ID,
        "capabilityId": CAPABILITY_ID,
        "packVersion": "2.0.0",
        "status": "ACTIVE",
        "distributionStatus": "LOCAL_ONLY",
        "source": {
            "kind": "LOCAL_GIT",
            "repositoryId": "web-high-fidelity",
            "repositoryPath": str(source),
            "commit": commit,
            "tree": tree,
        },
        "resolvedContentDigest": _expected_content_digest(source, manifest),
        "validator": {
            "kind": "FIXED_CANDIDATE_GATE",
            "relativePath": "scripts/verify-capability-pack",
            "sha256": "sha256:"
            + hashlib.sha256((source / "scripts/verify-capability-pack").read_bytes()).hexdigest(),
            "argumentsContract": "CANDIDATE_COMMIT_TREE",
        },
    }


def _declared_manifest_registration(
    source: Path,
    commit: str,
    tree: str,
) -> dict[str, Any]:
    manifest = _manifest()
    manifest.update(
        {
            "projectPackName": "java-engineering-standard",
            "skillName": "java-engineering-standard",
            "displayName": "Java Engineering Capability Pack",
            "capabilityId": "framework:java:java-engineering-standard",
            "version": "0.4.0",
            "contentRoots": ["docs", "skills"],
            "skillPath": "skills/java-engineering-standard/SKILL.md",
        }
    )
    return {
        "schemaVersion": "capability-pack-registration/v1",
        "registrationId": "pack:java-engineering-standard",
        "capabilityId": manifest["capabilityId"],
        "packVersion": manifest["version"],
        "status": "ACTIVE",
        "distributionStatus": "LOCAL_ONLY",
        "source": {
            "kind": "LOCAL_GIT",
            "repositoryId": manifest["projectPackName"],
            "repositoryPath": str(source),
            "commit": commit,
            "tree": tree,
        },
        "contentDeclaration": {
            "kind": "HARNESS_DECLARED_MANIFEST",
            "projectionContract": "SELF_CONTAINED_SKILL_BUNDLE",
            "manifest": manifest,
        },
        "resolvedContentDigest": _expected_content_digest(
            source,
            manifest,
            include_tracked_manifest=False,
        ),
        "validator": {
            "kind": "FIXED_CANDIDATE_GATE",
            "relativePath": "scripts/verify-capability-pack",
            "sha256": "sha256:"
            + hashlib.sha256(
                (source / "scripts/verify-capability-pack").read_bytes()
            ).hexdigest(),
            "argumentsContract": "CANDIDATE_COMMIT_TREE",
        },
    }


def _manifestless_pack_fixture(tmp_path: Path) -> tuple[Path, str, str]:
    source = tmp_path / "java-pack"
    source.mkdir()
    _write_valid_pack(source)
    (source / "capability-pack.yaml").unlink()
    web_skill = source / "skills/web-high-fidelity"
    java_skill = source / "skills/java-engineering-standard"
    web_skill.rename(java_skill)
    (source / "VERSION").write_text("0.4.0\n", encoding="utf-8")
    _git(source, "init", "-q")
    _git(source, "config", "user.name", "Pack Test")
    _git(source, "config", "user.email", "pack-test@example.invalid")
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "test: manifestless pack fixture")
    return (
        source,
        _git(source, "rev-parse", "HEAD"),
        _git(source, "rev-parse", "HEAD^{tree}"),
    )


def _write_test_schemas(root: Path, _source: Path) -> None:
    repository = Path(__file__).parents[1]
    destination = root / "core/schemas"
    destination.mkdir(parents=True)
    for name in [
        "capability-pack-manifest.schema.json",
        "capability-pack-registration.schema.json",
        "capability-validator-toolchain-binding.schema.json",
        "capability-validator-toolchain-registry.schema.json",
    ]:
        shutil.copy2(repository / "core/schemas" / name, destination / name)


def _write_registrations(root: Path, registrations: list[dict[str, Any]]) -> None:
    path = root / "core/registries/capability-packs.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(registrations, sort_keys=False), encoding="utf-8")


def _harness_with_pack(tmp_path: Path) -> tuple[Path, Path, str, str]:
    source, commit, tree = _pack_fixture(tmp_path)
    root = tmp_path / "harness"
    _write_test_schemas(root, source)
    _write_registrations(root, [_registration(source, commit, tree)])
    return root, source, commit, tree


def _make_toolchain_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() or os.access(path, os.X_OK) else 0o444)
    root.chmod(0o555)


def _managed_profile_harness(
    tmp_path: Path,
    *,
    mutate_binding_during_gate: bool = False,
    mutate_profile_during_gate: bool = False,
    scratch_record: Path | None = None,
    gate_outcome: str = "success",
    scratch_replacement: str | None = None,
    scratch_replacement_target: Path | None = None,
    scratch_ancestor_replacement: str | None = None,
    scratch_move_target: Path | None = None,
    scratch_reinject_acl: bool = False,
) -> tuple[Path, dict[str, Any]]:
    root = tmp_path / "harness"
    root.mkdir()
    _git(root, "init", "-q")
    source = tmp_path / "pack"
    source.mkdir()
    _write_valid_pack(source)
    _write_test_schemas(root, source)

    managed_store = root / ".worktrees/.capability-pack-cache/store"
    first = managed_store / "first"
    second = managed_store / "second"
    executable = b"#!/bin/sh\nexit 0\n"
    relative_commands = {
        "ruby": "bin/ruby",
        "rg": "bin/rg",
        "java": "java/bin/java",
        "javac": "java/bin/javac",
        "mvn": "home/.m2/wrapper/dists/apache-maven/fixture/bin/mvn",
    }
    for relative in relative_commands.values():
        path = first / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(executable)
        path.chmod(0o555)
    shadow_bash = first / "bin/bash"
    shadow_bash.write_bytes(b"#!/bin/sh\nexit 97\n")
    shadow_bash.chmod(0o555)
    maven_home = first / "home/.m2/wrapper/dists/apache-maven/fixture"
    (maven_home / "lib").mkdir()
    (maven_home / "lib/core.jar").write_bytes(b"core")
    repository = first / "home/.m2/repository"
    (repository / "org/example/tool/1.0").mkdir(parents=True)
    (repository / "org/example/tool/1.0/tool.jar").write_bytes(b"tool")
    shutil.copytree(first, second)
    _make_toolchain_read_only(first)
    _make_toolchain_read_only(second)

    platform_identity = {
        "os": platform.system().lower(),
        "architecture": platform.machine().lower(),
    }
    command_digest = "sha256:" + sha256_bytes(executable)
    artifact = {
        "artifactId": "artifact:ripgrep:test:darwin-arm64",
        "kind": "OFFICIAL_RELEASE_ARCHIVE",
        "platform": platform_identity,
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
        "platform": platform_identity,
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
                "sha256": directory_identity_digest(first / "java"),
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
    registry_path = root / "core/registries/capability-validator-toolchains.yaml"
    registry_path.parent.mkdir(parents=True)
    registry = {
        "schemaVersion": "capability-validator-toolchain-registry/v1",
        "artifacts": [artifact],
        "profiles": [profile],
    }
    registry_path.write_text(
        yaml.safe_dump(registry, sort_keys=False),
        encoding="utf-8",
    )

    def binding_record(toolchain_root: Path) -> dict[str, Any]:
        return {
            "schemaVersion": "capability-validator-toolchain-binding/v1",
            "profileId": profile_id,
            "commands": {
                name: str(toolchain_root / relative)
                for name, relative in relative_commands.items()
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

    binding_file = binding_path(root, profile_id)
    binding_file.parent.mkdir(parents=True)
    binding_file.write_text(json.dumps(binding_record(first)), encoding="utf-8")
    binding_file.chmod(0o444)

    expected_commands = {
        name: first / relative for name, relative in relative_commands.items()
    }
    expected_path = ":".join(
        dict.fromkeys(
            [str(path.parent) for path in expected_commands.values()]
            + ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
        )
    )
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"[ \"$PATH\" = {shlex.quote(expected_path)} ]",
        f"[ \"$HOME\" = {shlex.quote(str(first / 'home'))} ]",
        f"[ \"$JAVA_HOME\" = {shlex.quote(str(first / 'java'))} ]",
        f"[ \"$(command -v bash)\" = {shlex.quote(str(shadow_bash))} ]",
    ]
    lines.extend(
        f"[ \"$(command -v {name})\" = {shlex.quote(str(path))} ]"
        for name, path in expected_commands.items()
    )
    if scratch_record is not None:
        record = shlex.quote(str(scratch_record))
        lines.extend(
            [
                ': "${TMPDIR:?managed profile Gate requires TMPDIR}"',
                'case "$TMPDIR" in /*) ;; *) exit 81 ;; esac',
                '[ -d "$TMPDIR" ]',
                '[ ! -L "$TMPDIR" ]',
                '[ -w "$TMPDIR" ]',
                '[ "$(cd "$TMPDIR" && pwd -P)" = "$TMPDIR" ]',
                f'printf "%s\\n" "$TMPDIR" > {record}',
                f'/usr/bin/stat -f "%Lp" "$TMPDIR" >> {record}',
                'printf writable > "$TMPDIR/probe"',
            ]
        )
    if mutate_binding_during_gate:
        replacement = json.dumps(binding_record(second))
        lines.extend(
            [
                f"/bin/chmod 0644 {shlex.quote(str(binding_file))}",
                f"printf '%s' {shlex.quote(replacement)} > {shlex.quote(str(binding_file))}",
                f"/bin/chmod 0444 {shlex.quote(str(binding_file))}",
            ]
        )
    if mutate_profile_during_gate:
        replacement_registry = deepcopy(registry)
        replacement_registry["profiles"][0]["commands"]["ruby"]["sha256"] = (
            "sha256:" + "0" * 64
        )
        replacement = json.dumps(replacement_registry)
        lines.append(
            f"printf '%s' {shlex.quote(replacement)} > {shlex.quote(str(registry_path))}"
        )
    if gate_outcome == "failure":
        lines.append("exit 23")
    elif gate_outcome == "timeout":
        lines.append("/bin/sleep 60")
    elif gate_outcome != "success":
        raise ValueError(f"unsupported test Gate outcome: {gate_outcome}")
    if scratch_replacement == "directory":
        lines.extend(
            [
                '/bin/mv "$TMPDIR" "$TMPDIR-owned"',
                '/bin/mkdir -m 0700 "$TMPDIR"',
                'printf preserve > "$TMPDIR/replacement.txt"',
            ]
        )
    elif scratch_replacement == "symlink":
        if scratch_replacement_target is None:
            raise ValueError("symlink scratch replacement requires a target")
        lines.extend(
            [
                '/bin/mv "$TMPDIR" "$TMPDIR-owned"',
                (
                    f'/bin/ln -s {shlex.quote(str(scratch_replacement_target))} '
                    '"$TMPDIR"'
                ),
            ]
        )
    elif scratch_replacement is not None:
        raise ValueError(f"unsupported scratch replacement: {scratch_replacement}")
    if scratch_ancestor_replacement is not None:
        if scratch_ancestor_replacement == "runtime-parent":
            lines.append('scratch_ancestor="${TMPDIR%/*}"')
        elif scratch_ancestor_replacement == "managed-cache":
            lines.append('scratch_ancestor="${TMPDIR%/runtime/*}"')
        else:
            raise ValueError(
                "unsupported scratch ancestor replacement: "
                f"{scratch_ancestor_replacement}"
            )
        lines.extend(
            [
                '/bin/mv "$scratch_ancestor" "$scratch_ancestor-owned"',
                '/bin/mkdir -p "$TMPDIR"',
                'printf preserve > "$TMPDIR/replacement.txt"',
            ]
        )
    if scratch_move_target is not None:
        if scratch_reinject_acl:
            lines.append(
                '/bin/chmod +a "everyone allow readsecurity" "$TMPDIR"'
            )
        lines.append(
            f'/bin/mv "$TMPDIR" {shlex.quote(str(scratch_move_target))}'
        )
    elif scratch_reinject_acl:
        raise ValueError("scratch ACL reinjection requires a move target")
    validator = source / "scripts/verify-capability-pack"
    validator.write_text("\n".join(lines) + "\n", encoding="utf-8")
    validator.chmod(0o755)
    _git(source, "init", "-q")
    _git(source, "config", "user.name", "Pack Test")
    _git(source, "config", "user.email", "pack-test@example.invalid")
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "test: managed profile Gate")
    commit = _git(source, "rev-parse", "HEAD")
    tree = _git(source, "rev-parse", "HEAD^{tree}")
    registration = _registration(source, commit, tree)
    registration["validator"]["environmentContract"] = "MANAGED_TOOLCHAIN_PROFILE"
    registration["validator"]["toolchainProfile"] = {
        "profileId": profile_id,
        "profileDigest": profile_digest(profile),
    }
    if gate_outcome == "timeout":
        registration["validator"]["timeoutSeconds"] = 1
    _write_registrations(root, [registration])
    return root, registration


def _assert_private_gate_scratch_cleaned(record: Path) -> Path:
    scratch_value, mode = record.read_text(encoding="utf-8").splitlines()
    scratch = Path(scratch_value)
    assert scratch.is_absolute()
    assert mode == "700"
    assert not scratch.exists()
    return scratch


def _macos_acl_entries(path: Path) -> list[str]:
    completed = subprocess.run(
        ["/bin/ls", "-lde", str(path)],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    return completed.stdout.splitlines()[1:]


def _replace(path: Path, old: str, new: str) -> None:
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def _commit(source: Path, message: str) -> tuple[str, str]:
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", message)
    return _git(source, "rev-parse", "HEAD"), _git(source, "rev-parse", "HEAD^{tree}")


def _registered_entry(root: Path) -> dict[str, Any]:
    return yaml.safe_load(
        (root / "core/registries/capability-packs.yaml").read_text(encoding="utf-8")
    )[0]


def _refresh_source_identity(
    root: Path,
    source: Path,
    *,
    content_digest: bool = False,
    validator_digest: bool = False,
) -> dict[str, Any]:
    entry = _registered_entry(root)
    entry["source"]["commit"] = _git(source, "rev-parse", "HEAD")
    entry["source"]["tree"] = _git(source, "rev-parse", "HEAD^{tree}")
    manifest = yaml.safe_load((source / "capability-pack.yaml").read_text(encoding="utf-8"))
    if content_digest:
        entry["resolvedContentDigest"] = _expected_content_digest(source, manifest)
    if validator_digest:
        entry["validator"]["sha256"] = "sha256:" + hashlib.sha256(
            (source / entry["validator"]["relativePath"]).read_bytes()
        ).hexdigest()
    _write_registrations(root, [entry])
    return entry


def test_registry_entry_binds_immutable_source_and_validator_identity(tmp_path: Path):
    root, source, commit, tree = _harness_with_pack(tmp_path)

    registry = build_capability_pack_registry(root, write=False)

    entry = registry["entries"][0]
    assert entry["source"]["commit"] == commit
    assert entry["source"]["tree"] == tree
    assert entry["resolvedContentDigest"] == FIXTURE_CONTENT_DIGEST
    assert entry["validator"]["sha256"].startswith("sha256:")
    assert not (root / "generated/registries/capability-pack-registry.json").exists()


def test_registry_accepts_harness_declared_manifest_for_fixed_manifestless_pack(
    tmp_path: Path,
):
    source, commit, tree = _manifestless_pack_fixture(tmp_path)
    root = tmp_path / "harness"
    _write_test_schemas(root, source)
    registration = _declared_manifest_registration(source, commit, tree)
    _write_registrations(root, [registration])

    registry = build_capability_pack_registry(root, write=False)

    assert registry["entries"] == [registration]


def test_registry_rejects_harness_declared_manifest_identity_drift(tmp_path: Path):
    source, commit, tree = _manifestless_pack_fixture(tmp_path)
    root = tmp_path / "harness"
    _write_test_schemas(root, source)
    registration = _declared_manifest_registration(source, commit, tree)
    registration["contentDeclaration"]["manifest"]["version"] = "0.4.1"
    _write_registrations(root, [registration])

    with pytest.raises(ValueError, match="capability pack manifest identity mismatch"):
        build_capability_pack_registry(root, write=False)


def test_registry_canonical_revision_excludes_relocated_discovery_locator(
    tmp_path: Path,
):
    source, commit, tree = _manifestless_pack_fixture(tmp_path)
    root = tmp_path / "harness"
    _write_test_schemas(root, source)
    registration = _declared_manifest_registration(source, commit, tree)
    _write_registrations(root, [registration])
    before = build_capability_pack_registry(root, write=False)

    relocated = tmp_path / "java-pack-relocated"
    _git(tmp_path, "clone", "--quiet", "--no-hardlinks", str(source), str(relocated))
    _git(relocated, "checkout", "--quiet", "--detach", commit)
    registration["source"]["repositoryPath"] = str(relocated)
    _write_registrations(root, [registration])

    after = build_capability_pack_registry(root, write=False)

    assert after["sourceRevision"] == before["sourceRevision"]


def test_registration_fingerprint_binds_harness_declared_manifest(tmp_path: Path):
    source, commit, tree = _manifestless_pack_fixture(tmp_path)
    registration = _declared_manifest_registration(source, commit, tree)
    changed = deepcopy(registration)
    changed["contentDeclaration"]["manifest"]["displayName"] = "Changed"

    assert _registration_fingerprint(changed) != _registration_fingerprint(registration)


def test_pack_owner_preserves_canonical_java_registration_fingerprint_bytes():
    root = Path(__file__).parents[1]
    registration = next(
        item
        for item in load_capability_pack_registrations(root)
        if item["registrationId"] == JAVA_REGISTRATION_ID
    )

    assert _registration_fingerprint(registration) == (
        "sha256:5257755a93fafa35f7cb40fcdcd0a50aaf829ec66848e50c8c3e5db9a879e92b"
    )


def test_repository_registry_registers_fixed_java_engineering_standard():
    root = Path(__file__).parents[1]

    registry = build_capability_pack_registry(root, write=False)
    entry = next(
        item
        for item in registry["entries"]
        if item["registrationId"] == JAVA_REGISTRATION_ID
    )

    assert entry["capabilityId"] == JAVA_CAPABILITY_ID
    assert entry["packVersion"] == "0.4.0"
    assert entry["source"]["commit"] == JAVA_SOURCE_COMMIT
    assert entry["source"]["tree"] == JAVA_SOURCE_TREE
    assert entry["contentDeclaration"]["kind"] == "HARNESS_DECLARED_MANIFEST"
    manifest = entry["contentDeclaration"]["manifest"]
    assert manifest["projectPackName"] == "java-engineering-standard"
    assert manifest["skillName"] == "java-engineering-standard"
    assert manifest["skillPath"] == "skills/java-engineering-standard/SKILL.md"


def test_registry_write_materializes_only_the_external_registry_projection(tmp_path: Path):
    root, _, _, _ = _harness_with_pack(tmp_path)

    expected = build_capability_pack_registry(root, write=True)

    generated = json.loads(
        (root / "generated/registries/capability-pack-registry.json").read_text(encoding="utf-8")
    )
    assert generated == expected


def test_registry_rejects_manifest_identity_drift(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    _replace(source / "capability-pack.yaml", "reference-driven-visual-fidelity", "visual-delivery")
    _commit(source, "mutate: identity drift")
    _refresh_source_identity(root, source)

    with pytest.raises(ValueError, match="capability pack manifest identity mismatch"):
        build_capability_pack_registry(root, write=False)


def test_registry_rejects_validator_digest_drift(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    validator = source / "scripts/verify-capability-pack"
    validator.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    validator.chmod(0o755)
    _commit(source, "mutate: validator drift")
    _refresh_source_identity(root, source, content_digest=True)

    with pytest.raises(ValueError, match="capability pack validator identity mismatch"):
        build_capability_pack_registry(root, write=False)


def test_candidate_gate_executes_fixed_blob_in_isolated_git_checkout(tmp_path: Path):
    repository, _, _ = _pack_fixture(tmp_path)
    validator = repository / "scripts/verify-capability-pack"
    validator.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "repo_root=$(cd \"${0%/*}/..\" && pwd)\n"
        "[ \"$#\" -eq 2 ]\n"
        "[ -d \"$repo_root/.git\" ]\n"
        "[ \"$(git -C \"$repo_root\" rev-parse HEAD)\" = \"$1\" ]\n"
        "[ \"$(git -C \"$repo_root\" rev-parse 'HEAD^{tree}')\" = \"$2\" ]\n"
        "[ -z \"$(git -C \"$repo_root\" status --porcelain=v1 --untracked-files=all)\" ]\n",
        encoding="utf-8",
    )
    validator.chmod(0o755)
    commit, tree = _commit(repository, "test: require isolated checkout")
    source = tmp_path / "pack-linked"
    _git(repository, "worktree", "add", "-q", "--detach", str(source), commit)
    root = tmp_path / "harness"
    _write_test_schemas(root, source)
    _write_registrations(root, [_registration(source, commit, tree)])

    registry = build_capability_pack_registry(root, write=False)

    assert registry["entries"][0]["source"]["commit"] == commit


def test_candidate_gate_uses_registered_host_home_offline_cache_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repository, _, _ = _pack_fixture(tmp_path)
    trusted_home = tmp_path / "trusted-home"
    (trusted_home / ".m2/repository").mkdir(parents=True)
    (trusted_home / ".m2/repository/closure.txt").write_text("offline\n")
    trusted_bin = tmp_path / "trusted-bin"
    trusted_bin.mkdir()
    trusted_java_home = tmp_path / "trusted-java-home"
    (trusted_java_home / "bin").mkdir(parents=True)
    bash_bytes = Path("/bin/bash").read_bytes()
    for executable in ["ruby", "rg"]:
        (trusted_bin / executable).write_bytes(bash_bytes)
        (trusted_bin / executable).chmod(0o755)
    for executable in ["java", "javac"]:
        (trusted_java_home / f"bin/{executable}").write_bytes(bash_bytes)
        (trusted_java_home / f"bin/{executable}").chmod(0o755)
    trusted_maven_home = trusted_home / ".m2/wrapper/dists/apache-maven/fixture"
    (trusted_maven_home / "bin").mkdir(parents=True)
    (trusted_maven_home / "bin/mvn").write_bytes(bash_bytes)
    (trusted_maven_home / "bin/mvn").chmod(0o755)
    monkeypatch.setenv("HOME", str(trusted_home))
    validator = repository / "scripts/verify-capability-pack"
    validator.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"[ \"$HOME\" = \"{trusted_home}\" ]\n"
        "[ \"$LANG\" = \"en_US.UTF-8\" ]\n"
        "[ \"$LC_ALL\" = \"en_US.UTF-8\" ]\n"
        f"[ \"$JAVA_HOME\" = \"{trusted_java_home}\" ]\n",
        encoding="utf-8",
    )
    validator.chmod(0o755)
    commit, tree = _commit(repository, "test: require registered host home")
    root = tmp_path / "harness"
    _write_test_schemas(root, repository)
    registration = _registration(repository, commit, tree)
    bash_digest = "sha256:" + hashlib.sha256(Path("/bin/bash").read_bytes()).hexdigest()
    registration["validator"]["environmentContract"] = (
        "REGISTERED_TOOLCHAIN_OFFLINE_CACHE"
    )
    registration["validator"]["toolchain"] = {
        executable: {
            "absolutePath": str(trusted_bin / executable),
            "sha256": bash_digest,
        }
        for executable in ["ruby", "rg"]
    }
    registration["validator"]["toolchain"]["java"] = {
        "absolutePath": str(trusted_java_home / "bin/java"),
        "sha256": bash_digest,
    }
    registration["validator"]["toolchain"]["javac"] = {
        "absolutePath": str(trusted_java_home / "bin/javac"),
        "sha256": bash_digest,
    }
    registration["validator"]["toolchain"]["mvn"] = {
        "absolutePath": str(trusted_maven_home / "bin/mvn"),
        "sha256": bash_digest,
    }
    for root_path in (
        trusted_java_home,
        trusted_maven_home,
        trusted_home / ".m2/repository",
    ):
        for item in root_path.rglob("*"):
            item.chmod(0o555 if item.is_dir() or os.access(item, os.X_OK) else 0o444)
        root_path.chmod(0o555)
    for name, path in {
        "javaHome": trusted_java_home,
        "mavenHome": trusted_maven_home,
        "mavenRepository": trusted_home / ".m2/repository",
    }.items():
        registration["validator"]["toolchain"][name] = {
            "absolutePath": str(path),
            "sha256": directory_identity_digest(path),
        }
    registration["validator"]["sha256"] = "sha256:" + hashlib.sha256(
        validator.read_bytes()
    ).hexdigest()
    _write_registrations(root, [registration])

    real_digest = capability_pack_registry._directory_identity_digest
    digest_paths: list[Path] = []

    def counted_digest(path: Path) -> str:
        digest_paths.append(path)
        return real_digest(path)

    monkeypatch.setattr(
        capability_pack_registry,
        "_directory_identity_digest",
        counted_digest,
    )

    registry = build_capability_pack_registry(root, write=False)

    assert registry["entries"][0]["validator"]["environmentContract"] == (
        "REGISTERED_TOOLCHAIN_OFFLINE_CACHE"
    )
    assert digest_paths == [
        trusted_java_home,
        trusted_maven_home,
        trusted_home / ".m2/repository",
    ] * 2


def test_managed_profile_candidate_gate_uses_attested_resolution_and_absolute_bash(
    tmp_path: Path,
):
    root, expected = _managed_profile_harness(tmp_path)

    actual = get_registered_capability_pack(root, CAPABILITY_ID)

    assert actual == expected


def test_managed_profile_candidate_gate_uses_private_runtime_scratch(
    tmp_path: Path,
):
    record = tmp_path / "gate-scratch.txt"
    root, expected = _managed_profile_harness(tmp_path, scratch_record=record)

    actual = get_registered_capability_pack(root, CAPABILITY_ID)

    scratch = _assert_private_gate_scratch_cleaned(record)
    verified = capability_pack_registry._verify_validator_toolchain(root, expected)
    assert "TMPDIR" not in verified.environment
    persisted = canonical_json_bytes(actual)
    assert b"TMPDIR" not in persisted
    assert str(scratch).encode("utf-8") not in persisted


def test_managed_profile_candidate_gate_cleans_private_scratch_after_failure(
    tmp_path: Path,
):
    record = tmp_path / "gate-scratch.txt"
    root, _ = _managed_profile_harness(
        tmp_path,
        scratch_record=record,
        gate_outcome="failure",
    )

    with pytest.raises(ValueError, match="capability pack candidate Gate failed"):
        get_registered_capability_pack(root, CAPABILITY_ID)

    _assert_private_gate_scratch_cleaned(record)


def test_managed_profile_candidate_gate_cleans_private_scratch_after_timeout(
    tmp_path: Path,
):
    record = tmp_path / "gate-scratch.txt"
    root, _ = _managed_profile_harness(
        tmp_path,
        scratch_record=record,
        gate_outcome="timeout",
    )

    with pytest.raises(ValueError, match="capability pack candidate Gate timed out"):
        get_registered_capability_pack(root, CAPABILITY_ID)

    _assert_private_gate_scratch_cleaned(record)


@pytest.mark.parametrize("replacement", ["directory", "symlink"])
def test_managed_profile_candidate_gate_preserves_scratch_path_replacement(
    tmp_path: Path,
    replacement: str,
):
    record = tmp_path / "gate-scratch.txt"
    replacement_target = tmp_path / "replacement-target"
    replacement_target.mkdir()
    marker = replacement_target / "unrelated.txt"
    marker.write_text("preserve", encoding="utf-8")
    root, _ = _managed_profile_harness(
        tmp_path,
        scratch_record=record,
        scratch_replacement=replacement,
        scratch_replacement_target=replacement_target,
    )

    with pytest.raises(
        ValueError,
        match="managed runtime scratch public identity changed",
    ):
        get_registered_capability_pack(root, CAPABILITY_ID)

    scratch = Path(record.read_text(encoding="utf-8").splitlines()[0])
    if replacement == "directory":
        assert (scratch / "replacement.txt").read_text(encoding="utf-8") == (
            "preserve"
        )
    else:
        assert scratch.is_symlink()
        assert scratch.readlink() == replacement_target
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert not Path(f"{scratch}-owned").exists()


@pytest.mark.parametrize("ancestor", ["runtime-parent", "managed-cache"])
def test_managed_profile_candidate_gate_rejects_scratch_ancestor_replacement(
    tmp_path: Path,
    ancestor: str,
):
    record = tmp_path / "gate-scratch.txt"
    root, _ = _managed_profile_harness(
        tmp_path,
        scratch_record=record,
        scratch_ancestor_replacement=ancestor,
    )

    with capability_pack_registry.CapabilityVerificationSession(
        root,
        allowed_capability_ids={CAPABILITY_ID},
    ) as session:
        with pytest.raises(
            ValueError,
            match="managed runtime public chain identity changed",
        ):
            get_registered_capability_pack(
                root,
                CAPABILITY_ID,
                verification_session=session,
            )
        assert session.stats.verified_pack_count == 0

    scratch = Path(record.read_text(encoding="utf-8").splitlines()[0])
    assert (scratch / "replacement.txt").read_text(encoding="utf-8") == "preserve"
    if ancestor == "runtime-parent":
        owned_scratch = Path(f"{scratch.parent}-owned") / scratch.name
    else:
        owned_scratch = (
            Path(f"{scratch.parent.parent}-owned") / "runtime" / scratch.name
        )
    assert not owned_scratch.exists()


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS ACL contract")
def test_managed_profile_candidate_gate_neutralizes_moved_scratch_acl(
    tmp_path: Path,
):
    record = tmp_path / "gate-scratch.txt"
    moved = tmp_path / "moved-gate-scratch"
    root, _ = _managed_profile_harness(
        tmp_path,
        scratch_record=record,
        scratch_move_target=moved,
        scratch_reinject_acl=True,
    )

    with capability_pack_registry.CapabilityVerificationSession(
        root,
        allowed_capability_ids={CAPABILITY_ID},
    ) as session:
        with pytest.raises(
            ValueError,
            match="managed runtime scratch cleanup ownership cannot be proven",
        ):
            get_registered_capability_pack(
                root,
                CAPABILITY_ID,
                verification_session=session,
            )
        assert session.stats.verified_pack_count == 0

    assert moved.is_dir()
    assert list(moved.iterdir()) == []
    assert stat.S_IMODE(moved.stat().st_mode) == 0o700
    assert _macos_acl_entries(moved) == []


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS ACL contract")
def test_managed_runtime_scratch_neutralizes_inherited_acl_on_private_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from evolution_harness import toolchain_provisioning

    root, expected = _managed_profile_harness(tmp_path)
    profile_id = expected["validator"]["toolchainProfile"]["profileId"]
    runtime_parent = binding_path(root, profile_id).parent.parent / "runtime"
    runtime_parent.mkdir()
    runtime_parent.chmod(0o700)
    subprocess.run(
        [
            "/bin/chmod",
            "+a",
            (
                "everyone allow list,search,add_file,add_subdirectory,"
                "delete_child,file_inherit,directory_inherit"
            ),
            str(runtime_parent),
        ],
        check=True,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    assert _macos_acl_entries(runtime_parent)

    real_mkdir = os.mkdir
    scratch_acl_injected = False

    def mkdir_with_inherited_acl(path, mode=0o777, *, dir_fd=None):
        nonlocal scratch_acl_injected
        result = real_mkdir(path, mode, dir_fd=dir_fd)
        if str(path).startswith(".capability-pack-gate-"):
            subprocess.run(
                [
                    "/bin/chmod",
                    "+ai",
                    "everyone allow readsecurity",
                    str(runtime_parent / str(path)),
                ],
                check=True,
                capture_output=True,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
            )
            scratch_acl_injected = True
        return result

    monkeypatch.setattr(toolchain_provisioning.os, "mkdir", mkdir_with_inherited_acl)

    with toolchain_provisioning.managed_runtime_scratch(root) as scratch:
        assert scratch.parent == runtime_parent
        assert stat.S_IMODE(scratch.stat().st_mode) == 0o700
        assert stat.S_IMODE(runtime_parent.stat().st_mode) == 0o700
        assert _macos_acl_entries(scratch) == []
        assert _macos_acl_entries(runtime_parent) == []

    assert scratch_acl_injected is True
    assert not scratch.exists()


def test_managed_profile_candidate_gate_rejects_binding_relocation_during_gate(
    tmp_path: Path,
):
    root, _ = _managed_profile_harness(
        tmp_path, mutate_binding_during_gate=True
    )

    with pytest.raises(
        ValueError,
        match="toolchain identity changed during candidate Gate",
    ):
        get_registered_capability_pack(root, CAPABILITY_ID)


def test_managed_profile_candidate_gate_rejects_profile_drift_during_gate(
    tmp_path: Path,
):
    root, _ = _managed_profile_harness(
        tmp_path, mutate_profile_during_gate=True
    )

    with pytest.raises(
        ValueError,
        match="toolchain profile identity mismatch",
    ):
        get_registered_capability_pack(root, CAPABILITY_ID)


@pytest.mark.parametrize(
    "drift",
    [
        "javac",
        "mvn",
        "maven-lib",
        "plugin-artifact",
        "directory-mode",
        "empty-directory-add",
    ],
)
def test_registry_rejects_registered_toolchain_digest_drift(
    tmp_path: Path, drift: str
):
    root, source, _, _ = _harness_with_pack(tmp_path)
    toolchain_root = tmp_path / "registered-toolchain"
    toolchain_root.mkdir()
    bash_bytes = Path("/bin/bash").read_bytes()
    toolchain = {}
    java_home = toolchain_root / "java-home"
    maven_home = toolchain_root / ".m2/wrapper/dists/apache-maven/fixture"
    repository = toolchain_root / ".m2/repository"
    (java_home / "bin").mkdir(parents=True)
    (maven_home / "bin").mkdir(parents=True)
    (maven_home / "lib").mkdir()
    (maven_home / "lib/maven-core.jar").write_bytes(b"maven-core")
    empty_directory = maven_home / "empty"
    empty_directory.mkdir()
    repository.mkdir(parents=True)
    plugin_artifact = repository / "org/example/plugin/1.0/plugin-1.0.jar"
    plugin_artifact.parent.mkdir(parents=True)
    plugin_artifact.write_bytes(b"plugin")
    executable_paths = {
        "ruby": toolchain_root / "ruby",
        "rg": toolchain_root / "rg",
        "java": java_home / "bin/java",
        "javac": java_home / "bin/javac",
        "mvn": maven_home / "bin/mvn",
    }
    for executable, path in executable_paths.items():
        path.write_bytes(bash_bytes)
        path.chmod(0o755)
        toolchain[executable] = {
            "absolutePath": str(path),
            "sha256": "sha256:" + hashlib.sha256(bash_bytes).hexdigest(),
        }
    for root_path in (java_home, maven_home, repository):
        for item in root_path.rglob("*"):
            item.chmod(0o555 if item.is_dir() or os.access(item, os.X_OK) else 0o444)
        root_path.chmod(0o555)
    for name, path in {
        "javaHome": java_home,
        "mavenHome": maven_home,
        "mavenRepository": repository,
    }.items():
        toolchain[name] = {"absolutePath": str(path), "sha256": directory_identity_digest(path)}
    if drift in {"javac", "mvn"}:
        executable_paths[drift].chmod(0o755)
        executable_paths[drift].write_bytes(b"replaced executable")
        executable_paths[drift].chmod(0o555)
    elif drift == "maven-lib":
        (maven_home / "lib/maven-core.jar").chmod(0o644)
        (maven_home / "lib/maven-core.jar").write_bytes(b"replaced maven lib")
        (maven_home / "lib/maven-core.jar").chmod(0o444)
    elif drift == "plugin-artifact":
        plugin_artifact.chmod(0o644)
        plugin_artifact.write_bytes(b"replaced plugin artifact")
        plugin_artifact.chmod(0o444)
    elif drift == "directory-mode":
        empty_directory.chmod(0o755)
    else:
        (maven_home / "lib").chmod(0o755)
        (maven_home / "lib/added-empty-directory").mkdir()
        (maven_home / "lib/added-empty-directory").chmod(0o555)
        (maven_home / "lib").chmod(0o555)
    entry = _registered_entry(root)
    entry["validator"]["environmentContract"] = (
        "REGISTERED_TOOLCHAIN_OFFLINE_CACHE"
    )
    entry["validator"]["toolchain"] = toolchain
    _write_registrations(root, [entry])

    with pytest.raises(ValueError, match="toolchain .*(identity mismatch|is writable)"):
        build_capability_pack_registry(root, write=False)


def test_candidate_gate_materializes_registered_parent_tree_closure(tmp_path: Path):
    source, _, _ = _pack_fixture(tmp_path)
    (source / "docs/active.txt").write_text("candidate bytes\n", encoding="utf-8")
    validator = source / "scripts/verify-capability-pack"
    validator.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "git -C \"${0%/*}/..\" cat-file -e \"$1^\"\n"
        "git -C \"${0%/*}/..\" diff --check \"$1^\" \"$1\"\n",
        encoding="utf-8",
    )
    validator.chmod(0o755)
    commit, tree = _commit(source, "test: candidate requiring parent closure")
    root = tmp_path / "harness"
    _write_test_schemas(root, source)
    registration = _registration(source, commit, tree)
    registration["resolvedContentDigest"] = _expected_content_digest(source, _manifest())
    registration["validator"]["sha256"] = "sha256:" + hashlib.sha256(
        validator.read_bytes()
    ).hexdigest()
    registration["validator"]["gitHistoryContract"] = "CANDIDATE_PARENT_TREE"
    registration["validator"]["timeoutSeconds"] = 30
    _write_registrations(root, [registration])

    registry = build_capability_pack_registry(root, write=False)

    assert registry["entries"][0]["validator"]["gitHistoryContract"] == (
        "CANDIDATE_PARENT_TREE"
    )
    assert registry["entries"][0]["validator"]["timeoutSeconds"] == 30


def test_candidate_gate_timeout_terminates_descendant_process_group(tmp_path: Path):
    source, _, _ = _pack_fixture(tmp_path)
    child_pid = tmp_path / "child.pid"
    grandchild_pid = tmp_path / "grandchild.pid"
    late_side_effect = tmp_path / "late.txt"
    validator = source / "scripts/verify-capability-pack"
    validator.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"bash -c 'trap \"\" TERM; exec >/dev/null 2>&1; "
        f"(trap \"\" TERM; sleep 60; printf late > {late_side_effect}) & "
        f"echo $! > {grandchild_pid}; wait' &\n"
        f"echo $! > {child_pid}\n"
        "wait\n",
        encoding="utf-8",
    )
    validator.chmod(0o755)
    commit, tree = _commit(source, "test: descendant timeout cleanup")
    root = tmp_path / "harness"
    _write_test_schemas(root, source)
    registration = _registration(source, commit, tree)
    registration["validator"]["sha256"] = "sha256:" + hashlib.sha256(
        validator.read_bytes()
    ).hexdigest()
    registration["validator"]["timeoutSeconds"] = 1
    _write_registrations(root, [registration])

    with pytest.raises(ValueError, match="candidate Gate timed out"):
        build_capability_pack_registry(root, write=False)

    for pid_path in (child_pid, grandchild_pid):
        pid = int(pid_path.read_text(encoding="utf-8"))
        for _ in range(40):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail(f"candidate Gate descendant survived timeout: {pid}")
    assert not late_side_effect.exists()


def test_candidate_gate_timeout_kills_group_before_reaping_leader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from evolution_harness import capability_pack_registry

    events: list[str] = []

    class FakeProcess:
        pid = 424242

        def __init__(self, *args, **kwargs):
            events.append("start")
            self.calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                events.append("timeout")
                raise subprocess.TimeoutExpired("gate", timeout)
            events.append("reap")
            return b"", b""

    monkeypatch.setattr(capability_pack_registry.subprocess, "Popen", FakeProcess)

    def record_killpg(pid: int, signum: int):
        assert pid == FakeProcess.pid
        events.append("term" if signum == signal.SIGTERM else "kill")

    monkeypatch.setattr(capability_pack_registry.os, "killpg", record_killpg)

    with pytest.raises(ValueError, match="candidate Gate timed out"):
        capability_pack_registry._run_candidate_gate(
            ["gate"], cwd=tmp_path, timeout=1, environment={}
        )

    assert events == ["start", "timeout", "term", "kill", "reap"]


@pytest.mark.parametrize("index_flag", ["--assume-unchanged", "--skip-worktree"])
def test_registry_rejects_hidden_worktree_validator_drift(
    tmp_path: Path, index_flag: str
):
    root, source, _, _ = _harness_with_pack(tmp_path)
    validator = source / "scripts/verify-capability-pack"
    validator.write_text("#!/usr/bin/env bash\nexit 23\n", encoding="utf-8")
    validator.chmod(0o755)
    _commit(source, "mutate: committed failing validator")
    _refresh_source_identity(root, source, content_digest=True, validator_digest=True)
    _git(source, "update-index", index_flag, "scripts/verify-capability-pack")
    validator.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    validator.chmod(0o755)

    with pytest.raises(ValueError, match="capability pack source has hidden index flags"):
        build_capability_pack_registry(root, write=False)


def test_registry_rejects_duplicate_active_capability_id(tmp_path: Path):
    root, _, _, _ = _harness_with_pack(tmp_path)
    entry = _registered_entry(root)
    _write_registrations(root, [entry, dict(entry)])

    with pytest.raises(ValueError, match="duplicate active capability pack ID"):
        build_capability_pack_registry(root, write=False)


def test_registry_preserves_two_inactive_identities_with_bounded_child_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root, _, _, _ = _harness_with_pack(tmp_path)
    first = _registered_entry(root)
    first["status"] = "INACTIVE"
    second = deepcopy(first)
    second["registrationId"] = "pack:web-high-fidelity-legacy"
    _write_registrations(root, [second, first])
    real_gate = capability_pack_registry._run_candidate_gate
    gate_count = 0

    def counted_gate(*args, **kwargs):
        nonlocal gate_count
        gate_count += 1
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", counted_gate)

    registry = build_capability_pack_registry(root, write=False)

    expected_entries = sorted([first, second], key=lambda item: item["registrationId"])
    canonical_entries = deepcopy(expected_entries)
    for entry in canonical_entries:
        entry["source"].pop("repositoryPath")
    expected_revision = "content-sha256:" + hashlib.sha256(
        json.dumps(
            canonical_entries,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert registry["entries"] == expected_entries
    assert registry["sourceRevision"] == expected_revision
    assert gate_count == 2


def test_registry_rejects_wrong_commit_tree_pair(tmp_path: Path):
    root, source, _, original_tree = _harness_with_pack(tmp_path)
    (source / "docs/history/ignored.txt").write_text("new excluded bytes\n", encoding="utf-8")
    commit, _ = _commit(source, "mutate: new tree")
    entry = _registered_entry(root)
    entry["source"]["commit"] = commit
    entry["source"]["tree"] = original_tree
    _write_registrations(root, [entry])

    with pytest.raises(ValueError, match="capability pack commit/tree mismatch"):
        build_capability_pack_registry(root, write=False)


def test_registry_rejects_committed_active_content_digest_drift(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    entry = _registered_entry(root)
    original_digest = entry["resolvedContentDigest"]
    (source / "docs/active.txt").write_text("changed active content\n", encoding="utf-8")
    commit, tree = _commit(source, "mutate: active content digest")
    entry["source"]["commit"] = commit
    entry["source"]["tree"] = tree
    assert entry["resolvedContentDigest"] == original_digest
    _write_registrations(root, [entry])

    with pytest.raises(ValueError, match="capability pack content identity mismatch"):
        build_capability_pack_registry(root, write=False)


def test_registry_ignores_git_replacement_objects_for_source_identity(tmp_path: Path):
    root, source, original_commit, _ = _harness_with_pack(tmp_path)
    (source / "docs/active.txt").write_text("replacement content\n", encoding="utf-8")
    replacement_commit, replacement_tree = _commit(source, "mutate: replacement commit")
    entry = _registration(source, replacement_commit, replacement_tree)
    entry["source"]["commit"] = original_commit
    _git(source, "replace", original_commit, replacement_commit)
    _git(source, "checkout", "-q", "--detach", original_commit)
    _write_registrations(root, [entry])

    with pytest.raises(ValueError, match="capability pack commit/tree mismatch"):
        build_capability_pack_registry(root, write=False)


def test_registry_rejects_dirty_source(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    (source / "docs/history/ignored.txt").write_text("dirty excluded bytes\n", encoding="utf-8")

    with pytest.raises(ValueError, match="capability pack source is not clean"):
        build_capability_pack_registry(root, write=False)


def test_registry_rejects_ignored_untracked_active_content(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    (source / ".gitignore").write_text("docs/ignored.txt\n", encoding="utf-8")
    _commit(source, "test: ignore active content")
    _refresh_source_identity(root, source, content_digest=True)
    (source / "docs/ignored.txt").write_text("ignored active bytes\n", encoding="utf-8")

    with pytest.raises(ValueError, match="capability pack has ignored untracked active content"):
        build_capability_pack_registry(root, write=False)


def test_registry_allows_ignored_untracked_content_only_under_excluded_root(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    (source / ".gitignore").write_text("docs/history/*.tmp\n", encoding="utf-8")
    _commit(source, "test: ignore excluded content")
    _refresh_source_identity(root, source, content_digest=True)
    (source / "docs/history/excluded.tmp").write_text("excluded bytes\n", encoding="utf-8")

    registry = build_capability_pack_registry(root, write=False)

    assert registry["entries"][0]["capabilityId"] == CAPABILITY_ID


def test_registry_rejects_missing_git_object(tmp_path: Path):
    root, _, _, _ = _harness_with_pack(tmp_path)
    entry = _registered_entry(root)
    entry["source"]["commit"] = "f" * 40
    _write_registrations(root, [entry])

    with pytest.raises(ValueError, match="capability pack Git object is unavailable"):
        build_capability_pack_registry(root, write=False)


@pytest.mark.parametrize("unsafe_root", ["../outside", "/absolute", "docs//nested"])
def test_registry_rejects_unsafe_content_roots(tmp_path: Path, unsafe_root: str):
    root, source, _, _ = _harness_with_pack(tmp_path)
    manifest = yaml.safe_load((source / "capability-pack.yaml").read_text(encoding="utf-8"))
    manifest["contentRoots"] = [unsafe_root]
    (source / "capability-pack.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    _commit(source, "mutate: unsafe root")
    _refresh_source_identity(root, source)

    with pytest.raises(ValueError, match="capability pack manifest schema is invalid"):
        build_capability_pack_registry(root, write=False)


def test_registry_rejects_non_semver_manifest_version(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    manifest = yaml.safe_load((source / "capability-pack.yaml").read_text(encoding="utf-8"))
    manifest["version"] = "1.0.0-01"
    (source / "capability-pack.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    _commit(source, "mutate: invalid SemVer")
    _refresh_source_identity(root, source)

    with pytest.raises(ValueError, match="capability pack manifest schema is invalid"):
        build_capability_pack_registry(root, write=False)


def test_registry_rejects_symlink_in_active_content(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    (source / "docs/link.txt").symlink_to("active.txt")
    _commit(source, "mutate: active symlink")
    _refresh_source_identity(root, source)

    with pytest.raises(ValueError, match="capability pack active content contains symlink"):
        build_capability_pack_registry(root, write=False)


def test_registry_rejects_submodule_in_active_content(tmp_path: Path):
    root, source, commit, _ = _harness_with_pack(tmp_path)
    _git(source, "update-index", "--add", "--cacheinfo", f"160000,{commit},docs/vendor")
    _git(source, "commit", "-qm", "mutate: active gitlink")
    _refresh_source_identity(root, source)

    with pytest.raises(ValueError, match="capability pack active content contains submodule"):
        build_capability_pack_registry(root, write=False)


def test_registry_rejects_case_fold_collision(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    _git(source, "config", "core.ignorecase", "false")
    collision_path = source / "docs/Foo.txt"
    collision_path.write_text("upper\n", encoding="utf-8")
    upper_blob = _git(source, "hash-object", "-w", str(collision_path))
    collision_path.write_text("lower\n", encoding="utf-8")
    lower_blob = _git(source, "hash-object", "-w", str(collision_path))
    _git(source, "update-index", "--add", "--cacheinfo", f"100644,{upper_blob},docs/Foo.txt")
    _git(source, "update-index", "--add", "--cacheinfo", f"100644,{lower_blob},docs/foo.txt")
    _git(source, "commit", "-qm", "mutate: case-fold collision")
    _refresh_source_identity(root, source)

    with pytest.raises(ValueError, match="capability pack active content case-fold collision"):
        build_capability_pack_registry(root, write=False)


def test_registry_rejects_untracked_active_content(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    (source / "docs/untracked.txt").write_text("untracked\n", encoding="utf-8")

    with pytest.raises(ValueError, match="capability pack has untracked active content"):
        build_capability_pack_registry(root, write=False)


def test_registry_rejects_failed_candidate_gate(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    validator = source / "scripts/verify-capability-pack"
    validator.write_text("#!/usr/bin/env bash\nexit 23\n", encoding="utf-8")
    validator.chmod(0o755)
    _commit(source, "mutate: failing gate")
    _refresh_source_identity(root, source, content_digest=True, validator_digest=True)

    with pytest.raises(ValueError, match="capability pack candidate Gate failed"):
        build_capability_pack_registry(root, write=False)


def test_registry_rejects_source_root_symlink(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    alias = tmp_path / "pack-alias"
    alias.symlink_to(source, target_is_directory=True)
    entry = _registered_entry(root)
    entry["source"]["repositoryPath"] = str(alias)
    _write_registrations(root, [entry])

    with pytest.raises(ValueError, match="capability pack source root must not be a symlink"):
        build_capability_pack_registry(root, write=False)


def test_registry_rejects_relative_source_root(tmp_path: Path):
    root, _, _, _ = _harness_with_pack(tmp_path)
    entry = _registered_entry(root)
    entry["source"]["repositoryPath"] = "relative/pack"
    _write_registrations(root, [entry])

    with pytest.raises(ValueError, match="registration schema is invalid"):
        build_capability_pack_registry(root, write=False)


def test_registry_rejects_non_normalized_absolute_source_root(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    entry = _registered_entry(root)
    entry["source"]["repositoryPath"] = str(source.parent / "." / source.name / ".." / source.name)
    _write_registrations(root, [entry])

    with pytest.raises(ValueError, match="source root must not be a symlink or alias"):
        build_capability_pack_registry(root, write=False)


def test_registered_capability_pack_lookup_rejects_unknown_and_inactive(tmp_path: Path):
    root, _, _, _ = _harness_with_pack(tmp_path)
    with pytest.raises(KeyError, match="active capability pack registration not found or ambiguous"):
        get_registered_capability_pack(root, "workflow:unknown:missing")

    entry = _registered_entry(root)
    entry["status"] = "INACTIVE"
    _write_registrations(root, [entry])
    schema_path = root / "core/schemas/capability-pack-registration.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["properties"]["status"]["const"] = "INACTIVE"
    schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(KeyError, match="active capability pack registration not found or ambiguous"):
        get_registered_capability_pack(root, CAPABILITY_ID)


def test_registered_capability_pack_lookup_does_not_validate_unselected_pack(
    tmp_path: Path,
):
    root, _, _, _ = _harness_with_pack(tmp_path)
    selected = _registered_entry(root)
    unrelated = deepcopy(selected)
    unrelated["registrationId"] = "pack:unrelated"
    unrelated["capabilityId"] = "workflow:unrelated:broken"
    unrelated["resolvedContentDigest"] = "sha256:" + "0" * 64
    _write_registrations(root, [selected, unrelated])

    registration = get_registered_capability_pack(root, CAPABILITY_ID)

    assert registration["registrationId"] == REGISTRATION_ID
