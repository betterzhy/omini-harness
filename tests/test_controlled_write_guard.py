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


def _linked_git_boundary(tmp_path):
    source = tmp_path / "linked-source"
    lane = tmp_path / "linked-lane"
    source.mkdir()
    _git(source, "init", "-q")
    _git(source, "config", "user.name", "Linked Boundary Test")
    _git(source, "config", "user.email", "linked@example.test")
    (source / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(source, "add", "tracked.txt")
    _git(source, "commit", "-qm", "base")
    _git(source, "worktree", "add", "-q", str(lane))
    lane_descriptor, observed = guard._open_absolute_directory_no_follow(lane)
    boundary = guard._open_git_boundary(
        lane_descriptor,
        lane,
        guard._physical_identity(observed),
    )
    return source, lane, lane_descriptor, boundary


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


def test_git_inventory_does_not_consume_transient_foreign_admin(
    guarded_lane, monkeypatch, tmp_path
):
    foreign = tmp_path / "foreign-inventory"
    foreign.mkdir()
    _git(foreign, "init", "-q")
    _git(foreign, "config", "user.name", "Foreign Inventory")
    _git(foreign, "config", "user.email", "foreign-inventory@example.test")
    (foreign / ".gitignore").write_text(
        ".guard-cache/\nignored-leak/\n", encoding="utf-8"
    )
    (foreign / "tracked.txt").write_text("foreign baseline\n", encoding="utf-8")
    _git(foreign, "add", ".")
    _git(foreign, "commit", "-qm", "foreign inventory")

    (guarded_lane.root / "tracked.txt").write_text(
        "foreign baseline\n", encoding="utf-8"
    )
    lane_admin = guarded_lane.root / ".git"
    held_lane_admin = tmp_path / "held-lane-admin"
    foreign_admin = foreign / ".git"
    original_run = guard.subprocess.run

    def substitute_admin_only_during_git(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args")
        if not argv or argv[0] != "/usr/bin/git":
            return original_run(*args, **kwargs)
        lane_admin.rename(held_lane_admin)
        foreign_admin.rename(lane_admin)
        try:
            return original_run(*args, **kwargs)
        finally:
            lane_admin.rename(foreign_admin)
            held_lane_admin.rename(lane_admin)

    monkeypatch.setattr(guard.subprocess, "run", substitute_admin_only_during_git)

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


def test_linked_worktree_inventory_fails_before_target_or_git_subprocess(
    tmp_path, monkeypatch, coordinator_state_factory
):
    monkeypatch.setenv(
        "AGENT_EVOLUTION_COORDINATOR_ROOT", str(tmp_path / "linked-state")
    )
    source = tmp_path / "linked-guard-source"
    lane = tmp_path / "linked-guard-lane"
    source.mkdir()
    _git(source, "init", "-q")
    _git(source, "config", "user.name", "Linked Guard")
    _git(source, "config", "user.email", "linked-guard@example.test")
    (source / ".gitignore").write_text(".guard-cache/\n", encoding="utf-8")
    (source / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-qm", "linked guard base")
    _git(source, "worktree", "add", "-q", str(lane))
    lease = _persist_active_lease(
        coordinator_state_factory,
        lane,
        source,
        ["allowed.txt"],
        [".guard-cache"],
    )
    target_started = False
    subprocess_started = False

    def unexpected_target(*args, **kwargs):
        nonlocal target_started
        target_started = True
        return subprocess.CompletedProcess(args[0], 0, b"", b"")

    def unexpected_subprocess(*args, **kwargs):
        nonlocal subprocess_started
        subprocess_started = True
        raise AssertionError("linked inventory must reject before subprocess launch")

    monkeypatch.setattr(guard, "_validate_sandbox_exec", lambda: None)
    monkeypatch.setattr(guard, "_run_sandboxed", unexpected_target)
    monkeypatch.setattr(guard.subprocess, "run", unexpected_subprocess)

    with pytest.raises(ControlledCoordinationError) as caught:
        guard.run_guarded_command(
            lease,
            lane,
            ["/usr/bin/true"],
            cwd=lane,
            environment={"PATH": "/usr/bin:/bin"},
        )

    assert caught.value.code == "LANE_INVENTORY_UNAVAILABLE"
    assert target_started is False
    assert subprocess_started is False


def test_physical_inventory_reports_new_undeclared_empty_directory(
    guarded_lane, monkeypatch
):
    def create_empty_directory(argv, *, cwd, environment, profile):
        del environment, profile
        Path(cwd, "undeclared-empty").mkdir()
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(guard, "_validate_sandbox_exec", lambda: None)
    monkeypatch.setattr(guard, "_run_sandboxed", create_empty_directory)

    with pytest.raises(ControlledCoordinationError) as caught:
        guard.run_guarded_command(
            guarded_lane.lease,
            guarded_lane.root,
            ["writer"],
            cwd=guarded_lane.root,
            environment={"PATH": "/usr/bin:/bin"},
        )

    assert caught.value.code == "WRITESET_BREACH"
    assert caught.value.observedPaths == ["undeclared-empty"]


def test_git_inventory_disables_repo_local_executable_extensions(
    guarded_lane, tmp_path
):
    sentinel = tmp_path / "fsmonitor-sentinel"
    helper = tmp_path / "fsmonitor-helper.sh"
    helper.write_text(
        "#!/bin/sh\n"
        'sentinel="${0%/*}/fsmonitor-sentinel"\n'
        '/usr/bin/touch "$sentinel"\n'
        "printf '\\n'\n",
        encoding="utf-8",
    )
    helper.chmod(0o755)
    _git(guarded_lane.root, "config", "core.fsmonitor", str(helper))

    helper_was_started = False
    try:
        result = guard.run_guarded_command(
            guarded_lane.lease,
            guarded_lane.root,
            ["/usr/bin/true"],
            cwd=guarded_lane.root,
            environment=guarded_lane.environment,
        )
        helper_was_started = sentinel.exists()
    finally:
        sentinel.unlink(missing_ok=True)

    assert result.returncode == 0
    assert helper_was_started is False
    assert not sentinel.exists()


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


def test_linked_worktree_uses_sealed_commondir_and_common_object_root(tmp_path):
    source, lane, lane_descriptor, boundary = _linked_git_boundary(tmp_path)
    try:
        head = guard._read_git_head(boundary)
    finally:
        guard._close_git_boundary(boundary)
        os.close(lane_descriptor)

    assert head == _git(source, "rev-parse", "HEAD").stdout.strip()


@pytest.mark.parametrize(
    "target",
    ["lane", "dot-git-file", "admin-root", "commondir-file", "common-objects"],
)
def test_linked_worktree_git_boundary_rejects_physical_path_swap(
    tmp_path, target
):
    _source, lane, lane_descriptor, boundary = _linked_git_boundary(tmp_path)
    targets = {
        "lane": lane,
        "dot-git-file": lane / ".git",
        "admin-root": boundary.admin_root,
        "commondir-file": boundary.admin_root / "commondir",
        "common-objects": boundary.common_admin_root / "objects",
    }
    selected = targets[target]
    moved = selected.with_name(selected.name + "-moved")
    selected.rename(moved)
    if moved.is_dir():
        selected.symlink_to(moved, target_is_directory=True)
    else:
        selected.symlink_to(moved)
    try:
        with pytest.raises(ControlledCoordinationError) as caught:
            guard._read_git_head(boundary)
    finally:
        guard._close_git_boundary(boundary)
        os.close(lane_descriptor)

    assert caught.value.code == "LANE_INVENTORY_UNAVAILABLE"


@pytest.mark.parametrize("target", ["lane", "admin-root", "common-objects"])
def test_linked_worktree_git_boundary_rechecks_paths_after_git(
    tmp_path, monkeypatch, target
):
    _source, lane, lane_descriptor, boundary = _linked_git_boundary(tmp_path)
    original_run = guard.subprocess.run
    selected = {
        "lane": lane,
        "admin-root": boundary.admin_root,
        "common-objects": boundary.common_admin_root / "objects",
    }[target]
    moved = selected.with_name(selected.name + "-moved")
    head = guard._read_git_head(boundary)

    def swap_after_git(*args, **kwargs):
        result = original_run(*args, **kwargs)
        selected.rename(moved)
        selected.mkdir()
        return result

    monkeypatch.setattr(guard.subprocess, "run", swap_after_git)
    try:
        with pytest.raises(ControlledCoordinationError) as caught:
            guard._read_git_object(boundary, head, expected_type="commit")
    finally:
        guard._close_git_boundary(boundary)
        os.close(lane_descriptor)

    assert caught.value.code == "LANE_INVENTORY_UNAVAILABLE"


def test_git_boundary_rejects_on_disk_object_alternates(tmp_path):
    source = tmp_path / "alternate-source"
    source.mkdir()
    _git(source, "init", "-q")
    alternate = source / ".git" / "objects" / "info" / "alternates"
    alternate.parent.mkdir(exist_ok=True)
    alternate.write_text(str(tmp_path / "foreign-objects") + "\n", encoding="utf-8")
    descriptor, observed = guard._open_absolute_directory_no_follow(source)
    try:
        with pytest.raises(ControlledCoordinationError) as caught:
            guard._open_git_boundary(
                descriptor,
                source,
                guard._physical_identity(observed),
            )
    finally:
        os.close(descriptor)

    assert caught.value.code == "LANE_INVENTORY_UNAVAILABLE"


def test_git_boundary_rejects_non_system_git_executable(
    guarded_lane, monkeypatch, tmp_path
):
    fake_git = tmp_path / "git"
    fake_git.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_git.chmod(0o755)
    monkeypatch.setattr(guard, "_GIT_PATH", str(fake_git))

    with pytest.raises(ControlledCoordinationError) as caught:
        guard.run_guarded_command(
            guarded_lane.lease,
            guarded_lane.root,
            ["/usr/bin/true"],
            cwd=guarded_lane.root,
            environment=guarded_lane.environment,
        )

    assert caught.value.code == "LANE_INVENTORY_UNAVAILABLE"


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("rename", ["allowed-dir/result.txt", "allowed.txt"]),
        ("copy", ["allowed-dir/result.txt"]),
    ],
)
def test_physical_inventory_preserves_rename_and_copy_paths(
    guarded_lane, operation, expected
):
    source = guarded_lane.root / "allowed.txt"
    destination = guarded_lane.root / "allowed-dir" / "result.txt"
    source.write_text("physical inventory\n", encoding="utf-8")
    lane_descriptor, observed = guard._open_absolute_directory_no_follow(
        guarded_lane.root
    )
    boundary = guard._open_git_boundary(
        lane_descriptor,
        guarded_lane.root,
        guard._physical_identity(observed),
    )
    try:
        before_snapshot = guard._scan_lane_tree(lane_descriptor)
        before = guard._inventory(
            lane_descriptor, boundary, physical_snapshot=before_snapshot
        )
        if operation == "rename":
            source.rename(destination)
        else:
            destination.write_bytes(source.read_bytes())
        after_snapshot = guard._scan_lane_tree(lane_descriptor)
        after = guard._inventory(
            lane_descriptor, boundary, physical_snapshot=after_snapshot
        )
    finally:
        guard._close_git_boundary(boundary)
        os.close(lane_descriptor)

    assert guard._physical_snapshot_changes(before_snapshot, after_snapshot) == expected
    assert sorted({*before["paths"], *after["paths"]}) == [
        "allowed-dir/result.txt",
        "allowed.txt",
    ]


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
