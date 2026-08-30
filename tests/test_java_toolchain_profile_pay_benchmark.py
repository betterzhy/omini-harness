from __future__ import annotations

import hashlib
import shutil
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


def _run_git(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
    ).stdout


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _remove_exact_tree(worktree: Path, target: Path) -> None:
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
    try:
        yield target
    finally:
        if target.exists():
            status = _run_git(target, "status", "--porcelain=v1", "-z")
            assert status == b"", (
                "benchmark detached worktree contains unexpected writes: "
                + status.decode(errors="replace")
            )
            subprocess.run(
                ["git", "-C", str(common_root), "worktree", "remove", str(target)],
                check=True,
                capture_output=True,
            )
        assert not target.exists()
        registered_after = _run_git(repository, "worktree", "list", "--porcelain")
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
        shutil.copytree(fixture / "integration", integration)
        shutil.copytree(fixture / "source", source)
        install_target.mkdir()
        source_before = _tree_bytes(source)

        def assert_source_unchanged(operation: str) -> None:
            assert _tree_bytes(source) == source_before, operation

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
                assert_source_unchanged("lock")
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
                assert_source_unchanged("projection")
                assert lock_path.read_bytes() == lock_bytes
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
                    assert_source_unchanged(f"scenario:{scenario_name}")
                    assert lock_path.read_bytes() == lock_bytes
                    assert _tree_bytes(projection) == projection_before
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
                assert_source_unchanged("freshness")
                assert lock_path.read_bytes() == lock_bytes
                assert _tree_bytes(projection) == projection_before
                checkpoints["freshness"] = _stats_snapshot(session)

                install_plan = install_projection(
                    root,
                    projection,
                    install_target,
                    source_root=source,
                    verification_session=session,
                )
                assert_source_unchanged("install-dry-run")
                assert lock_path.read_bytes() == lock_bytes
                assert _tree_bytes(projection) == projection_before
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
        finally:
            _remove_exact_tree(root, install_target)
            _remove_exact_tree(root, projection)
            _remove_exact_tree(root, integration)
            _remove_exact_tree(root, source)


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
