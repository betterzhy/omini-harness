from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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
