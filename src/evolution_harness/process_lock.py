from __future__ import annotations

import fcntl
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .hashing import sha256_bytes


class ProcessLockError(RuntimeError):
    pass


def process_lock_identity(namespace: str, target: Path) -> str:
    resolved = Path(target).resolve()
    return f"{namespace}:{resolved}"


@contextmanager
def exclusive_process_lock(identity: str) -> Iterator[None]:
    root = Path(tempfile.gettempdir()) / f"agent-evolution-harness-locks-{os.getuid()}"
    root.mkdir(mode=0o700, exist_ok=True)
    stat = root.lstat()
    if root.is_symlink() or not root.is_dir() or stat.st_uid != os.getuid():
        raise ProcessLockError("process lock directory is unsafe")
    token = sha256_bytes(identity.encode("utf-8"))
    path = root / f"{token}.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ProcessLockError("process lock file is unsafe") from exc
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProcessLockError("another writer already holds this operation lock") from exc
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
