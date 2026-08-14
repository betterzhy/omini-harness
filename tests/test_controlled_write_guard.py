from __future__ import annotations

import copy
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError
from evolution_harness.coordinator_state import CoordinatorStateStore
from evolution_harness.hashing import canonical_json_bytes, sha256_bytes
from evolution_harness import controlled_write_guard as guard


WRITER = Path(__file__).parent / "fixtures/guarded_writer.py"


def _sha256(value):
    return "sha256:" + sha256_bytes(canonical_json_bytes(value))


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        capture_output=True,
        text=True,
    )


@dataclass(frozen=True)
class GuardedLane:
    root: Path
    lease: dict[str, object]
    environment: dict[str, str]
    source_root: Path
    other_lane: Path
    integration_root: Path
    external_root: Path

    def with_lease(self, **changes: object) -> "GuardedLane":
        current = copy.deepcopy(self.lease)
        current.update(changes)
        return replace(self, lease=current)

    def run(self, *writer_args: str):
        return guard.run_guarded_command(
            self.lease,
            self.root,
            [sys.executable, str(WRITER), *writer_args],
            cwd=self.root,
            environment=self.environment,
        )


def _persist_active_lease(
    coordinator_state_factory,
    lane: Path,
    source_root: Path,
    exact: list[str],
    ephemeral: list[str],
) -> dict[str, object]:
    journal, _ = coordinator_state_factory.journal(1)
    receipt = journal["receipts"][0]
    lease = journal["leases"][0]
    command = receipt["evidence"]["command"]
    footprint = copy.deepcopy(lease["fullFootprint"])
    footprint["exactWriteSet"] = exact
    footprint["ephemeralWriteSet"] = ephemeral
    command["fullFootprint"] = copy.deepcopy(footprint)
    command["laneRoot"] = str(lane)
    command["originalSourceRoot"] = str(source_root)
    command["admissionAuthorityProof"]["binding"]["laneRoot"] = str(lane)
    command["admissionAuthorityProof"]["binding"]["originalSourceRoot"] = str(
        source_root
    )
    command["admissionAuthorityProof"]["proofDigest"] = _sha256(
        {
            key: value
            for key, value in command["admissionAuthorityProof"].items()
            if key != "proofDigest"
        }
    )
    command["commandDigest"] = _sha256(
        {key: value for key, value in command.items() if key != "commandDigest"}
    )
    receipt["commandDigest"] = command["commandDigest"]

    observed = os.stat(lane, follow_symlinks=False)
    lease.update(
        {
            "fullFootprint": copy.deepcopy(footprint),
            "laneRoot": str(lane),
            "originalSourceRoot": str(source_root),
            "lanePhysicalIdentity": {
                "device": observed.st_dev,
                "inode": observed.st_ino,
                "type": "DIRECTORY",
            },
            "state": "ACTIVE",
            "released": False,
            "recoveryStatus": "CLEAR",
        }
    )
    receipt["journalDigest"] = "sha256:" + "0" * 64
    receipt["journalDigest"] = _sha256(journal)

    with CoordinatorStateStore.open(lease) as store:
        with store.exclusive_project_lock():
            store.replace_journal(0, journal, copy.deepcopy(receipt))
    return copy.deepcopy(lease)


@pytest.fixture
def guarded_lane(tmp_path, monkeypatch, coordinator_state_factory):
    state_root = tmp_path / "coordinator-state"
    monkeypatch.setenv("AGENT_EVOLUTION_COORDINATOR_ROOT", str(state_root))
    source_root = tmp_path / "registered-source"
    other_lane = tmp_path / "other-lane"
    integration_root = tmp_path / "integration-lane"
    external_root = tmp_path / "external"
    lane = tmp_path / "guarded-lane"
    for directory in (source_root, other_lane, integration_root, external_root, lane):
        directory.mkdir()

    _git(lane, "init", "-q")
    _git(lane, "config", "user.name", "Guard Test")
    _git(lane, "config", "user.email", "guard@example.test")
    (lane / ".gitignore").write_text(
        ".guard-cache/\nignored-leak/\n", encoding="utf-8"
    )
    (lane / "tracked.txt").write_text("base\n", encoding="utf-8")
    (lane / "allowed-dir").mkdir()
    (lane / "swappable").mkdir()
    _git(lane, "add", ".")
    _git(lane, "commit", "-qm", "base")

    exact = ["allowed.txt", "allowed-dir", "swappable"]
    ephemeral = [".guard-cache"]
    lease = _persist_active_lease(
        coordinator_state_factory, lane, source_root, exact, ephemeral
    )
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    yield GuardedLane(
        root=lane,
        lease=lease,
        environment=environment,
        source_root=source_root,
        other_lane=other_lane,
        integration_root=integration_root,
        external_root=external_root,
    )

    assert not any(path.name == "escaped.txt" for path in tmp_path.rglob("escaped.txt"))
    assert not (lane / ".guard-cache").exists()


def test_declared_file_and_anchored_directory_are_writable(guarded_lane):
    first = guarded_lane.run("write", str(guarded_lane.root / "allowed.txt"))
    second = guarded_lane.run(
        "write", str(guarded_lane.root / "allowed-dir" / "nested.txt")
    )

    assert first.returncode == second.returncode == 0
    assert first.observedPaths == ["allowed.txt"]
    assert second.observedPaths == ["allowed-dir/nested.txt"]
    assert first.beforeInventory["paths"] == []
    assert second.afterInventory["paths"] == ["allowed-dir/nested.txt", "allowed.txt"]


def test_observed_paths_detects_rewrite_of_already_dirty_exact_file(guarded_lane):
    target = guarded_lane.root / "allowed.txt"
    first = guarded_lane.run("write", str(target), "first payload\n")
    second = guarded_lane.run("write", str(target), "second payload\n")

    assert first.returncode == second.returncode == 0
    assert second.beforeInventory["paths"] == ["allowed.txt"]
    assert second.afterInventory["paths"] == ["allowed.txt"]
    assert second.observedPaths == ["allowed.txt"]


@pytest.mark.parametrize(
    "destination",
    ["lane", "registered-source", "other-lane", "integration-root", "external"],
)
def test_real_process_cannot_write_outside_exact_set(guarded_lane, destination):
    roots = {
        "lane": guarded_lane.root,
        "registered-source": guarded_lane.source_root,
        "other-lane": guarded_lane.other_lane,
        "integration-root": guarded_lane.integration_root,
        "external": guarded_lane.external_root,
    }
    target = roots[destination] / "escaped.txt"

    result = guarded_lane.run("write", str(target))

    assert result.returncode != 0
    assert not target.exists()


@pytest.mark.parametrize("kind", ["ancestor", "final"])
def test_preflight_rejects_symlink_target_components(
    guarded_lane, kind, monkeypatch, coordinator_state_factory, tmp_path
):
    if kind == "ancestor":
        (guarded_lane.root / "allowed-dir" / "link").symlink_to(
            guarded_lane.external_root, target_is_directory=True
        )
        target = guarded_lane.root / "allowed-dir" / "link" / "escaped.txt"
        monkeypatch.setenv(
            "AGENT_EVOLUTION_COORDINATOR_ROOT", str(tmp_path / "symlink-state")
        )
        lease = _persist_active_lease(
            coordinator_state_factory,
            guarded_lane.root,
            guarded_lane.source_root,
            ["allowed-dir/link/escaped.txt"],
            [],
        )
        guarded_lane = replace(guarded_lane, lease=lease)
    else:
        target = guarded_lane.root / "allowed.txt"
        target.symlink_to(guarded_lane.external_root / "escaped.txt")

    with pytest.raises(ControlledCoordinationError) as caught:
        guarded_lane.run("write", str(target))

    assert caught.value.code == "UNSAFE_WRITE_TARGET"
    assert not (guarded_lane.external_root / "escaped.txt").exists()


def test_preflight_to_exec_path_swap_is_detected(guarded_lane):
    ready = guarded_lane.root / ".guard-cache" / "ready"
    target = guarded_lane.root / "swappable" / "escaped.txt"

    def swap_after_preflight():
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        original = guarded_lane.root / "swappable"
        original.rename(guarded_lane.root / "swappable-original")
        original.symlink_to(guarded_lane.external_root, target_is_directory=True)

    attacker = threading.Thread(target=swap_after_preflight)
    attacker.start()
    try:
        with pytest.raises(ControlledCoordinationError) as caught:
            guarded_lane.run("signal-write", str(target), str(ready), "0.30")
    finally:
        attacker.join(timeout=5)

    assert caught.value.code == "WRITE_TARGET_IDENTITY_CHANGED"
    assert not (guarded_lane.external_root / "escaped.txt").exists()


def test_missing_leaf_stays_bound_to_every_existing_ancestor(
    guarded_lane, monkeypatch, coordinator_state_factory, tmp_path
):
    monkeypatch.setenv(
        "AGENT_EVOLUTION_COORDINATOR_ROOT", str(tmp_path / "ancestor-state")
    )
    lease = _persist_active_lease(
        coordinator_state_factory,
        guarded_lane.root,
        guarded_lane.source_root,
        ["allowed-dir/nested.txt"],
        [".guard-cache"],
    )
    changed = replace(guarded_lane, lease=lease)
    ready = changed.root / ".guard-cache" / "ready"
    target = changed.root / "allowed-dir" / "nested.txt"
    original = changed.root / "allowed-dir-original"

    def swap_anchored_parent():
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        (changed.root / "allowed-dir").rename(original)
        (changed.root / "allowed-dir").mkdir()

    attacker = threading.Thread(target=swap_anchored_parent)
    attacker.start()
    try:
        with pytest.raises(ControlledCoordinationError) as caught:
            changed.run("signal-write", str(target), str(ready), "0.30")
    finally:
        attacker.join(timeout=5)
        target.unlink(missing_ok=True)
        if (changed.root / "allowed-dir").is_dir():
            (changed.root / "allowed-dir").rmdir()
        if original.is_dir():
            original.rename(changed.root / "allowed-dir")

    assert caught.value.code == "WRITE_TARGET_IDENTITY_CHANGED"


def test_child_created_symlink_cannot_escape(guarded_lane):
    link = guarded_lane.root / "allowed-dir" / "child-link"

    result = guarded_lane.run(
        "symlink-write", str(link), str(guarded_lane.external_root)
    )

    assert result.returncode != 0
    assert not (guarded_lane.external_root / "escaped.txt").exists()


def test_fork_setsid_and_detached_child_are_denied_by_kernel(guarded_lane):
    target = guarded_lane.external_root / "escaped.txt"

    result = guarded_lane.run(
        "delayed-detached-write", str(target), "0.20"
    )

    assert result.returncode != 0
    assert result.stdout == b""
    assert b"PermissionError" in result.stderr
    assert not target.exists()


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"fencingToken": None}, "MISSING_FENCING_TOKEN"),
        ({"fencingToken": 999}, "STALE_FENCING_TOKEN"),
        ({"state": "ADMITTED"}, "LEASE_NOT_ACTIVE"),
        ({"state": "CLOSED", "released": True}, "LEASE_NOT_ACTIVE"),
    ],
)
def test_missing_stale_or_inactive_lease_fails_before_process(
    guarded_lane, changes, code
):
    changed = guarded_lane.with_lease(**changes)

    with pytest.raises(ControlledCoordinationError) as caught:
        changed.run("write", str(changed.root / "allowed.txt"))

    assert caught.value.code == code
    assert not (changed.root / "allowed.txt").exists()


@pytest.mark.parametrize("failure", ["missing", "replaced"])
def test_unavailable_or_replaced_absolute_sandbox_fails_closed(
    guarded_lane, monkeypatch, failure
):
    if failure == "missing":
        monkeypatch.setattr(guard, "_SANDBOX_EXEC_PATH", "/usr/bin/not-sandbox-exec")
    else:
        monkeypatch.setattr(guard, "_SANDBOX_EXEC_SHA256", "0" * 64)

    with pytest.raises(ControlledCoordinationError) as caught:
        guarded_lane.run("write", str(guarded_lane.root / "allowed.txt"))

    assert caught.value.code == "PROCESS_SANDBOX_UNAVAILABLE"
    assert not (guarded_lane.root / "allowed.txt").exists()


def test_process_fork_denial_does_not_block_direct_exec(guarded_lane):
    target = guarded_lane.root / "allowed.txt"

    result = guarded_lane.run("write", str(target))

    assert result.returncode == 0
    assert target.read_text(encoding="utf-8") == "guarded write\n"


@pytest.mark.parametrize("tracked", [True, False])
def test_before_inventory_rejects_tracked_and_untracked_breach(
    guarded_lane, tracked
):
    target = guarded_lane.root / ("tracked.txt" if tracked else "untracked.txt")
    target.write_text("breach\n", encoding="utf-8")

    with pytest.raises(ControlledCoordinationError) as caught:
        guard.run_guarded_command(
            guarded_lane.lease,
            guarded_lane.root,
            ["/usr/bin/true"],
            cwd=guarded_lane.root,
            environment=guarded_lane.environment,
        )

    assert caught.value.code == "WRITESET_BREACH"
    assert caught.value.observedPaths == [target.name]


def test_git_inventory_uses_sealed_environment(guarded_lane, monkeypatch, tmp_path):
    fake = tmp_path / "fake-git-worktree"
    fake.mkdir()
    _git(fake, "init", "-q")
    _git(fake, "config", "user.name", "Fake Git")
    _git(fake, "config", "user.email", "fake@example.test")
    (fake / ".gitignore").write_text(".guard-cache/\n", encoding="utf-8")
    _git(fake, "add", ".")
    _git(fake, "commit", "-qm", "fake base")
    monkeypatch.setenv("GIT_DIR", str(fake / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(fake))
    (guarded_lane.root / "tracked.txt").write_text("breach\n", encoding="utf-8")

    with pytest.raises(ControlledCoordinationError) as caught:
        guard.run_guarded_command(
            guarded_lane.lease,
            guarded_lane.root,
            ["/usr/bin/true"],
            cwd=guarded_lane.root,
            environment=guarded_lane.environment,
        )

    assert caught.value.code == "WRITESET_BREACH"
    assert caught.value.observedPaths == ["tracked.txt"]


def test_git_admin_symlink_is_rejected_no_follow(guarded_lane):
    git_admin = guarded_lane.root / ".git"
    moved_admin = guarded_lane.root / ".git-real"
    git_admin.rename(moved_admin)
    git_admin.symlink_to(moved_admin, target_is_directory=True)
    try:
        with pytest.raises(ControlledCoordinationError) as caught:
            guard.run_guarded_command(
                guarded_lane.lease,
                guarded_lane.root,
                ["/usr/bin/true"],
                cwd=guarded_lane.root,
                environment=guarded_lane.environment,
            )
    finally:
        git_admin.unlink(missing_ok=True)
        moved_admin.rename(git_admin)

    assert caught.value.code == "LANE_INVENTORY_UNAVAILABLE"


def test_porcelain_rename_and_copy_preserve_both_physical_paths():
    paths, tracked, untracked, ignored = guard._parse_status(
        b"R  destination.txt\0source.txt\0C  copy.txt\0original.txt\0"
    )

    assert paths == [
        "copy.txt",
        "destination.txt",
        "original.txt",
        "source.txt",
    ]
    assert tracked == paths
    assert untracked == []
    assert ignored == []


def test_ignored_lane_exclusive_ephemeral_path_must_be_removed(guarded_lane):
    target = guarded_lane.root / ".guard-cache" / "temporary.txt"

    result = guarded_lane.run("write-remove", str(target))

    assert result.returncode == 0
    assert result.ephemeralPathsRemoved is True
    assert not (guarded_lane.root / ".guard-cache").exists()


def test_undeclared_ignored_path_is_a_persistent_breach(guarded_lane):
    target = guarded_lane.root / "ignored-leak" / "persistent.txt"
    target.parent.mkdir()
    target.write_text("ignored breach\n", encoding="utf-8")

    with pytest.raises(ControlledCoordinationError) as caught:
        guard.run_guarded_command(
            guarded_lane.lease,
            guarded_lane.root,
            ["/usr/bin/true"],
            cwd=guarded_lane.root,
            environment=guarded_lane.environment,
        )

    assert caught.value.code == "WRITESET_BREACH"
    assert caught.value.observedPaths == ["ignored-leak"]


def test_empty_ephemeral_root_left_by_child_is_not_reported_removed(guarded_lane):
    target = guarded_lane.root / ".guard-cache"
    left_behind = False

    try:
        with pytest.raises(ControlledCoordinationError) as caught:
            guarded_lane.run("mkdir", str(target))
    finally:
        left_behind = target.is_dir()
        if target.is_dir():
            target.rmdir()

    assert caught.value.code == "EPHEMERAL_PATH_NOT_REMOVED"
    assert caught.value.observedPaths == [".guard-cache"]
    assert left_behind is True


def test_nonignored_ephemeral_path_is_rejected_before_process(
    guarded_lane, monkeypatch, coordinator_state_factory, tmp_path
):
    monkeypatch.setenv(
        "AGENT_EVOLUTION_COORDINATOR_ROOT", str(tmp_path / "nonignored-state")
    )
    lease = _persist_active_lease(
        coordinator_state_factory,
        guarded_lane.root,
        guarded_lane.source_root,
        ["allowed.txt"],
        ["not-ignored"],
    )
    changed = replace(guarded_lane, lease=lease)

    with pytest.raises(ControlledCoordinationError) as caught:
        changed.run("write-remove", str(changed.root / "not-ignored" / "temp.txt"))

    assert caught.value.code == "UNSAFE_EPHEMERAL_WRITESET"
    assert not (changed.root / "not-ignored").exists()


def test_lane_inventory_never_follows_child_symlink(guarded_lane):
    link = guarded_lane.root / "allowed-dir" / "child-link"
    result = guarded_lane.run(
        "symlink-write", str(link), str(guarded_lane.external_root)
    )

    assert result.returncode != 0
    assert result.afterInventory["symlinkPaths"] == ["allowed-dir/child-link"]
    assert "allowed-dir/child-link/escaped.txt" not in result.afterInventory["paths"]
