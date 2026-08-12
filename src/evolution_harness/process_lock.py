from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import tempfile
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterator

from .hashing import sha256_bytes


class ProcessLockError(RuntimeError):
    pass


def process_lock_identity(namespace: str, target: Path) -> str:
    resolved = Path(target).resolve()
    return f"{namespace}:{resolved}"


def _state_root() -> Path:
    root = Path(tempfile.gettempdir()) / f"agent-evolution-harness-locks-{os.getuid()}"
    root.mkdir(mode=0o700, exist_ok=True)
    current = root.lstat()
    if (
        root.is_symlink()
        or not stat.S_ISDIR(current.st_mode)
        or current.st_uid != os.getuid()
        or current.st_mode & 0o077
    ):
        raise ProcessLockError("process state directory is unsafe")
    return root


def _validate_state_file(descriptor: int) -> None:
    current = os.fstat(descriptor)
    if not stat.S_ISREG(current.st_mode) or current.st_uid != os.getuid() or current.st_mode & 0o077:
        raise ProcessLockError("process state file is unsafe")


def _state_name(identity: str, suffix: str) -> str:
    return f"{sha256_bytes(identity.encode('utf-8'))}.{suffix}"


@contextmanager
def exclusive_process_lock(identity: str) -> Iterator[None]:
    root = _state_root()
    path = root / _state_name(identity, "lock")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ProcessLockError("process lock file is unsafe") from exc
    try:
        _validate_state_file(descriptor)
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


@contextmanager
def exclusive_process_locks(identities: list[str]) -> Iterator[None]:
    with ExitStack() as stack:
        for identity in sorted(set(identities)):
            stack.enter_context(exclusive_process_lock(identity))
        yield


def write_recovery_attestation(identity: str, journal_bytes: bytes, *, phase: str) -> None:
    if phase not in {"PREPARED", "COMMITTED"}:
        raise ProcessLockError("invalid recovery attestation phase")
    root = _state_root()
    root_descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    name = _state_name(identity, "recovery.json")
    temporary = f".{name}.tmp-{uuid.uuid4().hex}"
    payload = json.dumps(
        {
            "schemaVersion": "projection-recovery-attestation/v1",
            "identity": identity,
            "journalSha256": "sha256:" + sha256_bytes(journal_bytes),
            "phase": phase,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=root_descriptor,
        )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, name, src_dir_fd=root_descriptor, dst_dir_fd=root_descriptor)
        os.fsync(root_descriptor)
    except OSError as exc:
        raise ProcessLockError("cannot persist recovery attestation") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=root_descriptor)
        except FileNotFoundError:
            pass
        os.close(root_descriptor)


def _read_recovery_attestation(identity: str, *, missing_ok: bool = False) -> dict[str, str] | None:
    root = _state_root()
    path = root / _state_name(identity, "recovery.json")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        if missing_ok:
            return None
        raise ProcessLockError("trusted recovery attestation is missing") from exc
    except OSError as exc:
        raise ProcessLockError("recovery attestation is unsafe") from exc
    try:
        _validate_state_file(descriptor)
        raw = b""
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            raw += chunk
    finally:
        os.close(descriptor)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProcessLockError("recovery attestation is invalid") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schemaVersion", "identity", "journalSha256", "phase"}
        or payload.get("schemaVersion") != "projection-recovery-attestation/v1"
        or payload.get("identity") != identity
        or not isinstance(payload.get("journalSha256"), str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", payload["journalSha256"])
        or payload.get("phase") not in {"PREPARED", "COMMITTED"}
    ):
        raise ProcessLockError("recovery attestation is invalid")
    return payload


def recovery_attestation_phase(identity: str) -> str | None:
    payload = _read_recovery_attestation(identity, missing_ok=True)
    return None if payload is None else payload["phase"]


def verify_recovery_attestation(identity: str, journal_bytes: bytes) -> str:
    payload = _read_recovery_attestation(identity)
    assert payload is not None
    expected_hash = "sha256:" + sha256_bytes(journal_bytes)
    if payload["journalSha256"] != expected_hash:
        raise ProcessLockError("recovery attestation does not match the pending journal")
    return payload["phase"]


def remove_recovery_attestation(identity: str, *, missing_ok: bool = False) -> None:
    root = _state_root()
    path = root / _state_name(identity, "recovery.json")
    try:
        path.unlink()
    except FileNotFoundError:
        if not missing_ok:
            raise ProcessLockError("recovery attestation is missing")
