from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_KEY = "project-execution:" + "1" * 64
OTHER_PROJECT_KEY = "project-execution:" + "2" * 64
IDENTITY = {"projectExecutionKey": PROJECT_KEY}


def _open_store(root: Path, monkeypatch, identity=IDENTITY):
    from evolution_harness.coordinator_state import CoordinatorStateStore

    monkeypatch.setenv("AGENT_EVOLUTION_COORDINATOR_ROOT", str(root))
    return CoordinatorStateStore.open(identity)


def _state_entries(root: Path, suffix: str) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.name.endswith(suffix))


def _subprocess_open_and_lock(root: Path, project_key: str) -> subprocess.CompletedProcess[str]:
    repository = Path(__file__).parents[1]
    script = """
import sys
from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError
from evolution_harness.coordinator_state import CoordinatorStateStore
try:
    store = CoordinatorStateStore.open({"projectExecutionKey": sys.argv[1]})
    with store.exclusive_project_lock():
        pass
except ControlledCoordinationError as exc:
    print(exc.code)
    raise SystemExit(23)
"""
    environment = os.environ.copy()
    environment["AGENT_EVOLUTION_COORDINATOR_ROOT"] = str(root)
    environment["PYTHONPATH"] = str(repository / "src")
    return subprocess.run(
        [sys.executable, "-c", script, project_key],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _initialize(store, coordinator_state_factory, version=1):
    journal, receipt = coordinator_state_factory.journal(version)
    with store.exclusive_project_lock():
        persisted = store.replace_journal(version - 1, journal, receipt)
    return persisted


def test_state_root_rejects_symlink_and_permissive_mode(tmp_path, monkeypatch):
    from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError
    from evolution_harness.coordinator_state import CoordinatorStateStore

    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("AGENT_EVOLUTION_COORDINATOR_ROOT", str(alias))
    with pytest.raises(ControlledCoordinationError) as symlinked:
        CoordinatorStateStore.open(IDENTITY)
    assert symlinked.value.code == "UNSAFE_COORDINATOR_ROOT"

    real.chmod(0o755)
    monkeypatch.setenv("AGENT_EVOLUTION_COORDINATOR_ROOT", str(real))
    with pytest.raises(ControlledCoordinationError) as permissive:
        CoordinatorStateStore.open(IDENTITY)
    assert permissive.value.code == "UNSAFE_COORDINATOR_ROOT"


def test_state_root_and_project_files_are_owner_only_and_key_derived(
    tmp_path, monkeypatch, coordinator_state_factory
):
    root = tmp_path / "state"
    store = _open_store(root, monkeypatch)
    _initialize(store, coordinator_state_factory)

    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert PROJECT_KEY not in "\n".join(path.name for path in root.iterdir())
    for path in root.iterdir():
        assert not path.is_symlink()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(_state_entries(root, ".journal.json")) == 1
    assert len(_state_entries(root, ".lock")) == 1
    assert len(_state_entries(root, ".initialized")) == 1


def test_same_project_lock_is_nonblocking_across_processes_and_releases(
    tmp_path, monkeypatch
):
    root = tmp_path / "state"
    store = _open_store(root, monkeypatch)

    with store.exclusive_project_lock():
        blocked = _subprocess_open_and_lock(root, PROJECT_KEY)
    released = _subprocess_open_and_lock(root, PROJECT_KEY)

    assert blocked.returncode == 23
    assert blocked.stdout.strip() == "COORDINATOR_LOCK_BUSY"
    assert released.returncode == 0


def test_distinct_project_locks_are_independent_across_processes(tmp_path, monkeypatch):
    root = tmp_path / "state"
    store = _open_store(root, monkeypatch)

    with store.exclusive_project_lock():
        independent = _subprocess_open_and_lock(root, OTHER_PROJECT_KEY)

    assert independent.returncode == 0


def test_replace_journal_rejects_stale_expected_version(
    tmp_path, monkeypatch, coordinator_state_factory
):
    from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError

    store = _open_store(tmp_path / "state", monkeypatch)
    _initialize(store, coordinator_state_factory)
    journal, receipt = coordinator_state_factory.journal(2)

    with store.exclusive_project_lock():
        with pytest.raises(ControlledCoordinationError) as caught:
            store.replace_journal(0, journal, receipt)

    assert caught.value.code == "STALE_JOURNAL_VERSION"
    assert store.read_journal()["journalVersion"] == 1


def test_file_fsync_failure_preserves_previous_journal(
    tmp_path, monkeypatch, coordinator_state_factory
):
    from evolution_harness import coordinator_state
    from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError

    store = _open_store(tmp_path / "state", monkeypatch)
    _initialize(store, coordinator_state_factory)
    journal, receipt = coordinator_state_factory.journal(2)
    real_fsync = coordinator_state.os.fsync

    def fail_regular_file(descriptor):
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("injected file fsync failure")
        return real_fsync(descriptor)

    monkeypatch.setattr(coordinator_state.os, "fsync", fail_regular_file)
    with store.exclusive_project_lock():
        with pytest.raises(ControlledCoordinationError) as caught:
            store.replace_journal(1, journal, receipt)

    assert caught.value.code == "COORDINATOR_STATE_WRITE_FAILED"
    assert store.read_journal()["journalVersion"] == 1
    assert not any(".tmp-" in path.name for path in (tmp_path / "state").iterdir())


def test_descriptor_replace_failure_preserves_previous_journal(
    tmp_path, monkeypatch, coordinator_state_factory
):
    from evolution_harness import coordinator_state
    from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError

    store = _open_store(tmp_path / "state", monkeypatch)
    _initialize(store, coordinator_state_factory)
    journal, receipt = coordinator_state_factory.journal(2)

    def fail_replace(*args, **kwargs):
        raise OSError("injected descriptor replace failure")

    monkeypatch.setattr(coordinator_state.os, "replace", fail_replace)
    with store.exclusive_project_lock():
        with pytest.raises(ControlledCoordinationError) as caught:
            store.replace_journal(1, journal, receipt)

    assert caught.value.code == "COORDINATOR_STATE_WRITE_FAILED"
    assert store.read_journal()["journalVersion"] == 1


def test_directory_fsync_failure_reports_uncertain_but_readable_commit(
    tmp_path, monkeypatch, coordinator_state_factory
):
    from evolution_harness import coordinator_state
    from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError

    store = _open_store(tmp_path / "state", monkeypatch)
    _initialize(store, coordinator_state_factory)
    journal, receipt = coordinator_state_factory.journal(2)
    real_fsync = coordinator_state.os.fsync

    def fail_directory(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("injected directory fsync failure")
        return real_fsync(descriptor)

    monkeypatch.setattr(coordinator_state.os, "fsync", fail_directory)
    with store.exclusive_project_lock():
        with pytest.raises(ControlledCoordinationError) as caught:
            store.replace_journal(1, journal, receipt)

    assert caught.value.code == "COORDINATOR_DURABILITY_UNCERTAIN"
    assert store.read_journal()["journalVersion"] == 2


def test_replace_detects_destination_inode_swap_before_descriptor_replace(
    tmp_path, monkeypatch, coordinator_state_factory
):
    from evolution_harness import coordinator_state
    from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError

    root = tmp_path / "state"
    store = _open_store(root, monkeypatch)
    _initialize(store, coordinator_state_factory)
    journal_path = _state_entries(root, ".journal.json")[0]
    replacement = root / "replacement"
    replacement.write_bytes(journal_path.read_bytes())
    replacement.chmod(0o600)
    original_inode = journal_path.stat().st_ino
    journal, receipt = coordinator_state_factory.journal(2)
    real_fsync = coordinator_state.os.fsync
    swapped = False

    def swap_after_temp_fsync(descriptor):
        nonlocal swapped
        result = real_fsync(descriptor)
        if not swapped and stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.replace(replacement, journal_path)
            swapped = True
        return result

    monkeypatch.setattr(coordinator_state.os, "fsync", swap_after_temp_fsync)
    with store.exclusive_project_lock():
        with pytest.raises(ControlledCoordinationError) as caught:
            store.replace_journal(1, journal, receipt)

    assert caught.value.code == "COORDINATOR_STATE_INODE_CHANGED"
    assert journal_path.stat().st_ino != original_inode
    assert store.read_journal()["journalVersion"] == 1


def test_replace_rejects_receipt_history_rewrite(
    tmp_path, monkeypatch, coordinator_state_factory
):
    from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError

    store = _open_store(tmp_path / "state", monkeypatch)
    _initialize(store, coordinator_state_factory)
    journal, receipt = coordinator_state_factory.journal(2)
    journal["receipts"] = [receipt]

    with store.exclusive_project_lock():
        with pytest.raises(ControlledCoordinationError) as caught:
            store.replace_journal(1, journal, receipt)

    assert caught.value.code == "COORDINATOR_RECEIPT_HISTORY_REWRITE"
    assert store.read_journal()["journalVersion"] == 1


@pytest.mark.parametrize("payload", [b"{not-json", b'{"schemaVersion":'])
def test_read_rejects_corrupt_or_truncated_journal(
    tmp_path, monkeypatch, coordinator_state_factory, payload
):
    from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError

    root = tmp_path / "state"
    store = _open_store(root, monkeypatch)
    _initialize(store, coordinator_state_factory)
    journal_path = _state_entries(root, ".journal.json")[0]
    journal_path.write_bytes(payload)
    journal_path.chmod(0o600)

    with pytest.raises(ControlledCoordinationError) as caught:
        store.read_journal()

    assert caught.value.code == "COORDINATOR_JOURNAL_INVALID"


def test_read_rejects_wrong_journal_mode_and_owner_identity(
    tmp_path, monkeypatch, coordinator_state_factory
):
    from evolution_harness import coordinator_state
    from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError

    root = tmp_path / "state"
    store = _open_store(root, monkeypatch)
    _initialize(store, coordinator_state_factory)
    journal_path = _state_entries(root, ".journal.json")[0]
    journal_path.chmod(0o644)
    with pytest.raises(ControlledCoordinationError) as mode_error:
        store.read_journal()
    assert mode_error.value.code == "UNSAFE_COORDINATOR_STATE_FILE"

    journal_path.chmod(0o600)
    monkeypatch.setattr(coordinator_state, "_current_uid", lambda: os.getuid() + 1)
    with pytest.raises(ControlledCoordinationError) as owner_error:
        store.read_journal()
    assert owner_error.value.code == "UNSAFE_COORDINATOR_STATE_FILE"


def test_read_detects_inode_swap_during_descriptor_read(
    tmp_path, monkeypatch, coordinator_state_factory
):
    from evolution_harness import coordinator_state
    from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError

    root = tmp_path / "state"
    store = _open_store(root, monkeypatch)
    _initialize(store, coordinator_state_factory)
    journal_path = _state_entries(root, ".journal.json")[0]
    replacement = root / "replacement"
    replacement.write_bytes(journal_path.read_bytes())
    replacement.chmod(0o600)
    journal_inode = journal_path.stat().st_ino
    real_read_all = coordinator_state._read_all
    swapped = False

    def swap_then_read(descriptor):
        nonlocal swapped
        if not swapped and os.fstat(descriptor).st_ino == journal_inode:
            os.replace(replacement, journal_path)
            swapped = True
        return real_read_all(descriptor)

    monkeypatch.setattr(coordinator_state, "_read_all", swap_then_read)
    with pytest.raises(ControlledCoordinationError) as caught:
        store.read_journal()

    assert caught.value.code == "COORDINATOR_STATE_INODE_CHANGED"


def test_missing_previously_initialized_journal_fails_closed(
    tmp_path, monkeypatch, coordinator_state_factory
):
    from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError

    root = tmp_path / "state"
    store = _open_store(root, monkeypatch)
    _initialize(store, coordinator_state_factory)
    _state_entries(root, ".journal.json")[0].unlink()

    with pytest.raises(ControlledCoordinationError) as caught:
        store.read_journal()

    assert caught.value.code == "COORDINATOR_JOURNAL_MISSING"


def test_post_write_reread_validates_the_persisted_receipt(
    tmp_path, monkeypatch, coordinator_state_factory
):
    from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError

    store = _open_store(tmp_path / "state", monkeypatch)
    journal, receipt = coordinator_state_factory.journal(1)
    another_receipt = dict(receipt)
    another_receipt["receiptId"] = "coordinator-receipt:" + "f" * 24

    with store.exclusive_project_lock():
        with pytest.raises(ControlledCoordinationError) as caught:
            store.replace_journal(0, journal, another_receipt)

    assert caught.value.code == "COORDINATOR_RECEIPT_MISMATCH"
    assert store.read_journal() is None


def test_root_identity_change_is_rejected_by_another_process(
    tmp_path, monkeypatch
):
    root = tmp_path / "state"
    store = _open_store(root, monkeypatch)
    store.close()
    identity_path = root / ".root-identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["rootInode"] += 1
    identity_path.write_text(json.dumps(identity), encoding="utf-8")
    identity_path.chmod(0o600)

    opened = _subprocess_open_and_lock(root, PROJECT_KEY)

    assert opened.returncode == 23
    assert opened.stdout.strip() == "COORDINATOR_ROOT_IDENTITY_MISMATCH"
