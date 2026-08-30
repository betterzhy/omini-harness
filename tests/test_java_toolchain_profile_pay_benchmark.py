from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest


CAPABILITY_ID = "framework:java:java-engineering-standard"
INTERNAL_SKILL_ID = "skill:agent-design:architecture-review"
PROFILE_ID = "toolchain-profile:java-engineering-standard:darwin-arm64:v1"
PROFILE_DIGEST = "sha256:c852142343ea97aef6d3a555e5500ecb633baf1a23d846d7bbe72a8bcf5e4490"
REGISTRATION_FINGERPRINT = "sha256:cd5bbf5e763b38c96fccbf4c5a9357497c82e10fbf2272e4693fbcd2f63a708b"
SOURCE_COMMIT = "01d0e7d15ef9f6aa7814b0b001fa0b7c2c30e882"
SOURCE_TREE = "4bfc51d75c9e01e585db4cc073f952043ea01393"
CONTENT_DIGEST = "sha256:4e5920ddd604d7905647af94eb460f7ab20124fb96ffdea73f50ed6efd5a4581"
RESOURCE_SET_DIGEST = "sha256:0ae349a6e13c367759774c12d84f83ae14db782f2bea8f5b0fe6406748c82539"
INTEGRATION_ID = "java-toolchain-profile-pay-benchmark"
BENCHMARK_SCENARIO_NAMES = (
    "closed-architecture-protection",
    "consumed-stage-does-not-authorize-wave0",
    "current-authority-denies-execution",
    "next-slice-readiness-resolution",
    "review-go-does-not-authorize",
    "stage4-stop-replay",
)
TreeEntry = tuple[str, int, bytes | str | int | None]
TreeSnapshot = dict[str, TreeEntry]


def _run_git(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
    ).stdout


def _tree_bytes(root: Path) -> TreeSnapshot:
    snapshot: TreeSnapshot = {}

    def same_inode(expected: os.stat_result, actual: os.stat_result) -> bool:
        return (
            expected.st_dev,
            expected.st_ino,
            stat.S_IFMT(expected.st_mode),
        ) == (
            actual.st_dev,
            actual.st_ino,
            stat.S_IFMT(actual.st_mode),
        )

    def read_regular(
        directory_fd: int,
        name: str,
        expected: os.stat_result,
    ) -> bytes:
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        try:
            if not same_inode(expected, os.fstat(descriptor)):
                raise AssertionError("benchmark snapshot file changed during read")
            chunks = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    def walk(directory_fd: int, relative: str) -> None:
        directory_status = os.fstat(directory_fd)
        snapshot[relative] = (
            "directory",
            stat.S_IMODE(directory_status.st_mode),
            None,
        )
        with os.scandir(directory_fd) as entries:
            children = sorted(
                (
                    entry.name,
                    entry.stat(follow_symlinks=False),
                )
                for entry in entries
            )
        for name, child_status in children:
            child_relative = name if relative == "." else f"{relative}/{name}"
            mode = stat.S_IMODE(child_status.st_mode)
            if stat.S_ISDIR(child_status.st_mode):
                child_fd = os.open(
                    name,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
                try:
                    if not same_inode(child_status, os.fstat(child_fd)):
                        raise AssertionError(
                            "benchmark snapshot directory changed during read"
                        )
                    walk(child_fd, child_relative)
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(child_status.st_mode):
                snapshot[child_relative] = (
                    "regular",
                    mode,
                    read_regular(directory_fd, name, child_status),
                )
            elif stat.S_ISLNK(child_status.st_mode):
                snapshot[child_relative] = (
                    "symlink",
                    mode,
                    os.readlink(name, dir_fd=directory_fd),
                )
            else:
                snapshot[child_relative] = (
                    "other",
                    mode,
                    stat.S_IFMT(child_status.st_mode),
                )

    root_status = os.lstat(root)
    if stat.S_ISLNK(root_status.st_mode):
        return {
            ".": (
                "symlink",
                stat.S_IMODE(root_status.st_mode),
                os.readlink(root),
            )
        }
    if not stat.S_ISDIR(root_status.st_mode):
        raise AssertionError("benchmark snapshot root is not a directory")
    root_fd = os.open(
        root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        if not same_inode(root_status, os.fstat(root_fd)):
            raise AssertionError("benchmark snapshot root changed during read")
        walk(root_fd, ".")
    finally:
        os.close(root_fd)
    return snapshot


def _remove_exact_tree(
    worktree: Path,
    target: Path,
    *,
    expected_snapshot: TreeSnapshot | None = None,
) -> None:
    if expected_snapshot is None:
        raise AssertionError("benchmark cleanup is not verified")
    try:
        actual_snapshot = _tree_bytes(target)
    except OSError as exc:
        raise AssertionError("benchmark cleanup snapshot changed") from exc
    if actual_snapshot != expected_snapshot:
        raise AssertionError("benchmark cleanup snapshot changed")
    resolved_root = worktree.resolve(strict=True)
    resolved_target = target.resolve(strict=False)
    if resolved_target == resolved_root:
        raise AssertionError("benchmark cleanup refused the worktree root")
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as exc:
        raise AssertionError("benchmark cleanup target escaped the worktree") from exc
    if target.is_symlink():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()


def _worktree_status(worktree: Path) -> bytes:
    return _run_git(
        worktree,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--ignored=matching",
    )


@contextmanager
def _detached_benchmark_worktree(repository: Path) -> Iterator[Path]:
    current_root = Path(
        _run_git(repository, "rev-parse", "--show-toplevel").decode().strip()
    ).resolve(strict=True)
    assert current_root == repository.resolve(strict=True)
    common_dir = Path(
        _run_git(repository, "rev-parse", "--path-format=absolute", "--git-common-dir")
        .decode()
        .strip()
    ).resolve(strict=True)
    common_root = common_dir.parent
    worktrees_root = common_root / ".worktrees"
    ignored = subprocess.run(
        ["git", "-C", str(common_root), "check-ignore", "-q", ".worktrees/"],
        check=False,
        capture_output=True,
    )
    assert ignored.returncode == 0, ".worktrees/ must be ignored"
    candidate = _run_git(repository, "rev-parse", "HEAD").decode().strip()
    target = worktrees_root / f"java-profile-benchmark-{uuid.uuid4().hex[:12]}"
    registered_before = _run_git(repository, "worktree", "list", "--porcelain")
    assert str(target).encode() not in registered_before
    assert not target.exists()
    subprocess.run(
        [
            "git",
            "-C",
            str(common_root),
            "worktree",
            "add",
            "--detach",
            str(target),
            candidate,
        ],
        check=True,
        capture_output=True,
    )
    assert target.resolve(strict=True).parent == worktrees_root.resolve(strict=True)
    assert _run_git(target, "rev-parse", "HEAD").decode().strip() == candidate
    failure: BaseException | None = None
    try:
        yield target
    except BaseException as exc:
        failure = exc
        raise
    finally:
        if target.exists():
            status = _worktree_status(target)
            if failure is not None:
                failure.add_note(
                    "benchmark detached worktree preserved after failure: "
                    f"{target}; status={status!r}"
                )
            elif status:
                raise AssertionError(
                    "benchmark detached worktree contains unexpected writes: "
                    + status.decode(errors="replace")
                )
            else:
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(common_root),
                        "worktree",
                        "remove",
                        str(target),
                    ],
                    check=True,
                    capture_output=True,
                )
        if not target.exists():
            registered_after = _run_git(
                repository, "worktree", "list", "--porcelain"
            )
            assert str(target).encode() not in registered_after


def _stats_snapshot(session) -> dict[str, object]:
    stats = session.stats
    return {
        "full_candidate_gate_count": stats.full_candidate_gate_count,
        "isolated_checkout_count": stats.isolated_checkout_count,
        "toolchain_directory_digest_count": stats.toolchain_directory_digest_count,
        "verified_pack_count": stats.verified_pack_count,
        "by_pack": {
            digest: dict(values) for digest, values in stats.by_pack.items()
        },
    }


def test_detached_benchmark_cleanup_preserves_mismatched_install_target_write():
    repository = Path(__file__).parents[1].resolve(strict=True)
    preserved_worktree: Path | None = None
    install_target: Path | None = None
    unexpected: Path | None = None
    try:
        with pytest.raises(AssertionError, match="benchmark cleanup snapshot changed"):
            with _detached_benchmark_worktree(repository) as root:
                preserved_worktree = root
                install_target = root / ".java-profile-benchmark-install-target"
                install_target.mkdir()
                expected_snapshot = _tree_bytes(install_target)
                unexpected = install_target / "unexpected-dry-run-write.txt"
                unexpected.write_text("preserve this evidence", encoding="utf-8")
                _remove_exact_tree(
                    root,
                    install_target,
                    expected_snapshot=expected_snapshot,
                )
        assert preserved_worktree.is_dir()
        assert unexpected.read_text(encoding="utf-8") == "preserve this evidence"
    finally:
        if preserved_worktree is not None and preserved_worktree.exists():
            if install_target is not None and install_target.is_dir():
                shutil.rmtree(install_target)
            assert _run_git(
                preserved_worktree, "status", "--porcelain=v1", "-z"
            ) == b""
            common_dir = Path(
                _run_git(
                    repository,
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-common-dir",
                )
                .decode()
                .strip()
            ).resolve(strict=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(common_dir.parent),
                    "worktree",
                    "remove",
                    str(preserved_worktree),
                ],
                check=True,
                capture_output=True,
            )


def test_benchmark_tree_snapshot_records_symlink_without_following(
    tmp_path: Path,
):
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    nested.chmod(0o750)
    regular = nested / "evidence.bin"
    regular.write_bytes(b"inside")
    regular.chmod(0o640)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"must-not-be-read")
    link = root / "outside-link"
    link.symlink_to(outside)

    snapshot = _tree_bytes(root)

    assert snapshot == {
        ".": ("directory", stat.S_IMODE(os.lstat(root).st_mode), None),
        "nested": (
            "directory",
            stat.S_IMODE(os.lstat(nested).st_mode),
            None,
        ),
        "nested/evidence.bin": ("regular", 0o640, b"inside"),
        "outside-link": (
            "symlink",
            stat.S_IMODE(os.lstat(link).st_mode),
            str(outside),
        ),
    }


@pytest.fixture(scope="module")
def java_profile_pay_benchmark_fixture():
    from evolution_harness.capability_pack_registry import (
        CapabilityVerificationSession,
    )
    from evolution_harness.install import install_projection
    from evolution_harness.integration import (
        build_integration_projection,
        check_integration_projection,
    )
    from evolution_harness.project import build_capability_lock
    from evolution_harness.scenario import run_integration_scenario

    repository = Path(__file__).parents[1].resolve(strict=True)
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "java-toolchain-profile-pay-benchmark"
    ).resolve(strict=True)
    with _detached_benchmark_worktree(repository) as root:
        integration = root / "integrations" / INTEGRATION_ID
        source = root / ".java-profile-benchmark-source"
        projection = root / "generated" / "projections" / "codex" / INTEGRATION_ID
        install_target = root / ".java-profile-benchmark-install-target"
        owned_roots_verified = False
        expected_owned_roots: dict[Path, TreeSnapshot] = {}
        expected_worktree_status: bytes | None = None
        shutil.copytree(fixture / "integration", integration)
        shutil.copytree(fixture / "source", source)
        install_target.mkdir()
        source_before = _tree_bytes(source)

        def assert_owned_roots_unchanged(operation: str) -> None:
            assert expected_owned_roots, operation
            for owned_root, expected_snapshot in expected_owned_roots.items():
                assert _tree_bytes(owned_root) == expected_snapshot, (
                    operation,
                    owned_root,
                )
            assert expected_worktree_status is not None, operation
            assert _worktree_status(root) == expected_worktree_status, operation

        try:
            with CapabilityVerificationSession(
                root,
                allowed_capability_ids={CAPABILITY_ID},
            ) as session:
                checkpoints: dict[str, dict[str, object]] = {}
                lock = build_capability_lock(
                    root,
                    integration / "control-plane",
                    write=True,
                    verification_session=session,
                )
                lock_path = (
                    integration
                    / "control-plane"
                    / ".agent-evolution"
                    / "capabilities.lock.yaml"
                )
                lock_bytes = lock_path.read_bytes()
                assert _tree_bytes(source) == source_before, "lock"
                checkpoints["lock"] = _stats_snapshot(session)

                manifest = build_integration_projection(
                    root,
                    integration,
                    source,
                    intent="architecture-review",
                    topic="benchmark-read-only",
                    requested_output="read-only authority review",
                    runtime="CODEX",
                    verification_session=session,
                )
                projection_before = _tree_bytes(projection)
                assert lock_path.read_bytes() == lock_bytes
                install_target_expected = _tree_bytes(install_target)
                assert set(install_target_expected) == {"."}
                assert install_target_expected["."][0] == "directory"
                expected_owned_roots = {
                    source: source_before,
                    integration: _tree_bytes(integration),
                    projection: projection_before,
                    install_target: install_target_expected,
                }
                expected_worktree_status = _worktree_status(root)
                assert_owned_roots_unchanged("projection")
                checkpoints["projection"] = _stats_snapshot(session)

                scenario_results = {}
                for scenario_name in BENCHMARK_SCENARIO_NAMES:
                    scenario_results[scenario_name] = run_integration_scenario(
                        root,
                        integration,
                        source,
                        integration / "scenarios" / f"{scenario_name}.yaml",
                        verification_session=session,
                    )
                    assert_owned_roots_unchanged(f"scenario:{scenario_name}")
                    assert lock_path.read_bytes() == lock_bytes
                    checkpoints[f"scenario:{scenario_name}"] = _stats_snapshot(
                        session
                    )

                freshness = check_integration_projection(
                    root,
                    integration,
                    source,
                    intent="architecture-review",
                    topic="benchmark-read-only",
                    requested_output="read-only authority review",
                    runtime="CODEX",
                    verification_session=session,
                )
                assert freshness.fresh, freshness.reasons
                assert_owned_roots_unchanged("freshness")
                assert lock_path.read_bytes() == lock_bytes
                checkpoints["freshness"] = _stats_snapshot(session)

                install_plan = install_projection(
                    root,
                    projection,
                    install_target,
                    source_root=source,
                    verification_session=session,
                )
                assert_owned_roots_unchanged("install-dry-run")
                assert lock_path.read_bytes() == lock_bytes
                checkpoints["install"] = _stats_snapshot(session)

                java_lock = next(
                    item
                    for item in lock["capabilities"]
                    if item["capabilityId"] == CAPABILITY_ID
                )
                java_projection = next(
                    item
                    for item in manifest["generatedSkills"]
                    if item["id"] == CAPABILITY_ID
                )
                internal_projection = next(
                    item
                    for item in manifest["generatedSkills"]
                    if item["id"] == INTERNAL_SKILL_ID
                )
                assert java_lock["sourceCommit"] == SOURCE_COMMIT
                assert java_lock["sourceTree"] == SOURCE_TREE
                assert java_lock["resolvedContentDigest"] == CONTENT_DIGEST
                assert (
                    java_lock["registrationFingerprint"]
                    == REGISTRATION_FINGERPRINT
                )
                assert java_lock["validatorIdentity"]["toolchainProfile"] == {
                    "profileId": PROFILE_ID,
                    "profileDigest": PROFILE_DIGEST,
                }
                assert java_projection["resourceSetDigest"] == RESOURCE_SET_DIGEST
                assert len(java_projection["resourceFiles"]) == 45
                assert internal_projection.get("resourceFiles", []) == []

                verified_packs = tuple(session._verified.values())  # noqa: SLF001
                assert len(verified_packs) == 1
                verified = verified_packs[0]
                assert verified.key.capability_id == CAPABILITY_ID
                assert verified.verified_toolchain.profile_id == PROFILE_ID
                assert verified.verified_toolchain.profile_digest == PROFILE_DIGEST
                registration_path = Path(
                    verified.registration["source"]["repositoryPath"]
                )
                for resource in java_projection["resourceFiles"]:
                    projected = (projection / resource["path"]).read_bytes()
                    source_bytes = _run_git(
                        registration_path,
                        "show",
                        f"{SOURCE_COMMIT}:{resource['sourcePath']}",
                    )
                    assert projected == source_bytes
                    assert hashlib.sha256(projected).hexdigest() == resource["sha256"]

                no_app_evidence = repr(
                    {
                        "lock": lock,
                        "manifest": manifest,
                        "registration": verified.registration,
                        "environment": dict(verified.verified_toolchain.environment),
                    }
                )
                assert "/Applications/ChatGPT.app" not in no_app_evidence
                assert "REGISTERED_TOOLCHAIN_OFFLINE_CACHE" not in no_app_evidence
                assert "MANAGED_TOOLCHAIN_PROFILE" in no_app_evidence

                expected_stats = {
                    "full_candidate_gate_count": 1,
                    "isolated_checkout_count": 1,
                    "toolchain_directory_digest_count": 6,
                    "verified_pack_count": 1,
                }
                assert all(
                    {key: snapshot[key] for key in expected_stats}
                    == expected_stats
                    for snapshot in checkpoints.values()
                ), checkpoints
                final_stats = session.stats
                assert len(final_stats.by_pack) == 1
                only_pack_stats = next(iter(final_stats.by_pack.values()))
                assert only_pack_stats["full_candidate_gate_count"] == 1
                assert only_pack_stats["isolated_checkout_count"] == 1
                assert only_pack_stats["toolchain_directory_digest_count"] == 6
                assert only_pack_stats["verified_pack_count"] == 1
                actual_stats = {
                    key: getattr(final_stats, key) for key in expected_stats
                }

                yield {
                    "scenario_results": scenario_results,
                    "source_before": source_before,
                    "source_after": _tree_bytes(source),
                    "lock_bytes": lock_bytes,
                    "lock_after": lock_path.read_bytes(),
                    "projection_before": projection_before,
                    "projection_after": _tree_bytes(projection),
                    "install_plan": install_plan,
                    "stats": actual_stats,
                }
            assert session.stats.active_use_lease_count == 0
            assert_owned_roots_unchanged("fixture-teardown")
            owned_roots_verified = True
        finally:
            if owned_roots_verified:
                _remove_exact_tree(
                    root,
                    install_target,
                    expected_snapshot=expected_owned_roots[install_target],
                )
                _remove_exact_tree(
                    root,
                    projection,
                    expected_snapshot=expected_owned_roots[projection],
                )
                _remove_exact_tree(
                    root,
                    integration,
                    expected_snapshot=expected_owned_roots[integration],
                )
                _remove_exact_tree(
                    root,
                    source,
                    expected_snapshot=expected_owned_roots[source],
                )


@pytest.mark.integration
@pytest.mark.pack_e2e
@pytest.mark.parametrize(
    "scenario_name", BENCHMARK_SCENARIO_NAMES, ids=BENCHMARK_SCENARIO_NAMES
)
def test_java_toolchain_profile_pay_scenario_benchmark(
    scenario_name: str,
    java_profile_pay_benchmark_fixture,
):
    result = java_profile_pay_benchmark_fixture["scenario_results"][scenario_name]
    assert result["gate"] == "PASS"
    assert result["checks"]
    assert all(check["pass"] for check in result["checks"])
    assert (
        java_profile_pay_benchmark_fixture["source_after"]
        == java_profile_pay_benchmark_fixture["source_before"]
    )


@pytest.mark.integration
@pytest.mark.pack_e2e
def test_java_toolchain_profile_pay_install_plan_benchmark(
    java_profile_pay_benchmark_fixture,
):
    plan = java_profile_pay_benchmark_fixture["install_plan"]
    assert plan["gate"] == "PASS"
    assert plan["mode"] == "DRY_RUN"
    assert len(plan["actions"]) == 46
    assert all(action["operation"] == "CREATE" for action in plan["actions"])
    assert (
        sum("java-engineering-standard" in action["target"] for action in plan["actions"])
        == 45
    )
    assert (
        sum("architecture-review" in action["target"] for action in plan["actions"])
        == 1
    )
    assert java_profile_pay_benchmark_fixture["lock_after"] == (
        java_profile_pay_benchmark_fixture["lock_bytes"]
    )
    assert java_profile_pay_benchmark_fixture["projection_after"] == (
        java_profile_pay_benchmark_fixture["projection_before"]
    )
    assert java_profile_pay_benchmark_fixture["stats"] == {
        "full_candidate_gate_count": 1,
        "isolated_checkout_count": 1,
        "toolchain_directory_digest_count": 6,
        "verified_pack_count": 1,
    }
