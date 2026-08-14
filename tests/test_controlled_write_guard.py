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
    (lane / ".gitignore").write_text(".guard-cache/\n", encoding="utf-8")
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


def test_child_created_symlink_cannot_escape(guarded_lane):
    link = guarded_lane.root / "allowed-dir" / "child-link"

    result = guarded_lane.run(
        "symlink-write", str(link), str(guarded_lane.external_root)
    )

    assert result.returncode != 0
    assert not (guarded_lane.external_root / "escaped.txt").exists()


def test_detached_child_is_contained_and_reaped_before_return(guarded_lane):
    target = guarded_lane.external_root / "escaped.txt"

    result = guarded_lane.run(
        "delayed-detached-write", str(target), "0.20"
    )
    child_pid = int(result.stdout.decode("ascii").strip())

    assert result.returncode == 0
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
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


def test_unavailable_process_tree_tracking_fails_before_process(
    guarded_lane, monkeypatch
):
    def unavailable():
        raise ControlledCoordinationError(
            "PROCESS_SANDBOX_UNAVAILABLE", "process tree tracking unavailable"
        )

    monkeypatch.setattr(guard, "_load_child_pid_function", unavailable, raising=False)

    with pytest.raises(ControlledCoordinationError) as caught:
        guarded_lane.run("write", str(guarded_lane.root / "allowed.txt"))

    assert caught.value.code == "PROCESS_SANDBOX_UNAVAILABLE"
    assert not (guarded_lane.root / "allowed.txt").exists()


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


def test_ignored_lane_exclusive_ephemeral_path_must_be_removed(guarded_lane):
    target = guarded_lane.root / ".guard-cache" / "temporary.txt"

    result = guarded_lane.run("write-remove", str(target))

    assert result.returncode == 0
    assert result.ephemeralPathsRemoved is True
    assert not (guarded_lane.root / ".guard-cache").exists()


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
