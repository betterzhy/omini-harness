from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from evolution_harness.capability_pack_registry import (
    build_capability_pack_registry,
    get_registered_capability_pack,
)


CAPABILITY_ID = "workflow:web-high-fidelity:reference-driven-visual-fidelity"
REGISTRATION_ID = "pack:web-high-fidelity"
FIXTURE_CONTENT_DIGEST = "sha256:42e88d096cd91ade629f1bb47474f24a7730c76c43cf250ae0bc549c30654cd7"
JAVA_CAPABILITY_ID = "framework:java:java-engineering-standard"
JAVA_REGISTRATION_ID = "pack:java-engineering-standard"
JAVA_SOURCE_COMMIT = "765e9d00a3173ecfe873c1646f5dbe375de677e7"
JAVA_SOURCE_TREE = "d79644b05149419feba8cdd7860b7dbbb48e4961"


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
    from evolution_harness.project import _registration_fingerprint

    source, commit, tree = _manifestless_pack_fixture(tmp_path)
    registration = _declared_manifest_registration(source, commit, tree)
    changed = deepcopy(registration)
    changed["contentDeclaration"]["manifest"]["displayName"] = "Changed"

    assert _registration_fingerprint(changed) != _registration_fingerprint(registration)


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
    trusted_home.mkdir()
    trusted_bin = tmp_path / "trusted-bin"
    trusted_bin.mkdir()
    trusted_java_home = tmp_path / "trusted-java-home"
    (trusted_java_home / "bin").mkdir(parents=True)
    for executable in ["ruby", "rg"]:
        (trusted_bin / executable).symlink_to("/bin/bash")
    (trusted_java_home / "bin/java").symlink_to("/bin/bash")
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
    registration["validator"]["sha256"] = "sha256:" + hashlib.sha256(
        validator.read_bytes()
    ).hexdigest()
    _write_registrations(root, [registration])

    registry = build_capability_pack_registry(root, write=False)

    assert registry["entries"][0]["validator"]["environmentContract"] == (
        "REGISTERED_TOOLCHAIN_OFFLINE_CACHE"
    )


def test_registry_rejects_registered_toolchain_digest_drift(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    toolchain_root = tmp_path / "registered-toolchain"
    toolchain_root.mkdir()
    bash_bytes = Path("/bin/bash").read_bytes()
    toolchain = {}
    for executable in ("ruby", "rg", "java"):
        path = toolchain_root / executable
        path.write_bytes(bash_bytes)
        path.chmod(0o755)
        toolchain[executable] = {
            "absolutePath": str(path),
            "sha256": "sha256:" + hashlib.sha256(bash_bytes).hexdigest(),
        }
    toolchain["java"]["sha256"] = "sha256:" + "0" * 64
    entry = _registered_entry(root)
    entry["validator"]["environmentContract"] = (
        "REGISTERED_TOOLCHAIN_OFFLINE_CACHE"
    )
    entry["validator"]["toolchain"] = toolchain
    _write_registrations(root, [entry])

    with pytest.raises(
        ValueError, match="capability pack validator toolchain identity mismatch"
    ):
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
    _write_registrations(root, [registration])

    registry = build_capability_pack_registry(root, write=False)

    assert registry["entries"][0]["validator"]["gitHistoryContract"] == (
        "CANDIDATE_PARENT_TREE"
    )


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
