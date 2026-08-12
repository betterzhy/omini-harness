from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


def test_process_lock_rejects_competing_process_and_releases_after_owner_exit(tmp_path: Path):
    from evolution_harness.process_lock import exclusive_process_lock, process_lock_identity

    root = Path(__file__).parents[1]
    identity = process_lock_identity("projection-build", tmp_path / "pack")
    script = """
import sys
from evolution_harness.process_lock import ProcessLockError, exclusive_process_lock
try:
    with exclusive_process_lock(sys.argv[1]):
        pass
except ProcessLockError:
    raise SystemExit(23)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")

    with exclusive_process_lock(identity):
        blocked = subprocess.run(
            [sys.executable, "-c", script, identity],
            env=environment,
            check=False,
        )
    released = subprocess.run(
        [sys.executable, "-c", script, identity],
        env=environment,
        check=False,
    )

    assert blocked.returncode == 23
    assert released.returncode == 0


def test_process_lock_rejects_state_directory_with_group_or_other_permissions(tmp_path: Path, monkeypatch):
    from evolution_harness import process_lock

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    state = tmp_path / f"agent-evolution-harness-locks-{os.getuid()}"
    state.mkdir(mode=0o755)
    state.chmod(0o755)

    with pytest.raises(process_lock.ProcessLockError, match="state directory is unsafe"):
        with process_lock.exclusive_process_lock("test:unsafe-mode"):
            pass
