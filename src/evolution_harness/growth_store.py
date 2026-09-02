from __future__ import annotations

import copy
import errno
import fcntl
import json
import os
import re
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .anchored_fs import AnchoredPathError, AnchoredRoot
from .growth_assessment import (
    GROWTH_POLICY_VERSION,
    GrowthAssessmentError,
    _rfc3339_order_key,
    _utc_rfc3339,
    build_growth_receipt,
    normalize_growth_assessment_request,
    validate_growth_receipt,
)
from .hashing import canonical_json_bytes, sha256_bytes
from .schema import SchemaStore, SchemaValidationError


_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_FIXED_DIRECTORIES = ("inbox", "staging", "locks")
_RECEIPT_NAME = re.compile(r"^[0-9a-f]{24}\.json$")
_ASSESSMENT_ID = re.compile(r"^growth-assessment:[0-9a-f]{24}$")
_RECEIPT_LIMIT = 131_072
_SCAN_LIMIT = 10_000
_SCAN_SCHEMA = "core/schemas/growth-scan-report.schema.json"


def _state_error(code: str, message: str) -> GrowthAssessmentError:
    return GrowthAssessmentError(code, message)


def _state_creation_error(message: str, error: OSError) -> GrowthAssessmentError:
    if isinstance(error, PermissionError) or error.errno in {errno.EACCES, errno.EPERM, errno.EROFS}:
        return _state_error("STATE_ROOT_UNSAFE", message)
    return _state_error("STATE_ROOT_UNAVAILABLE", message)


def _resolve_state_root(state_root: Path | None) -> Path:
    if state_root is None:
        codex_home = os.environ.get("CODEX_HOME")
        if codex_home is None:
            raise _state_error("STATE_ROOT_UNAVAILABLE", "CODEX_HOME is required for the default state root")
        home = Path(codex_home)
        if not home.is_absolute():
            raise _state_error("STATE_ROOT_UNSAFE", "CODEX_HOME must be absolute")
        requested = home / "agent-evolution" / "growth" / "v1"
    else:
        requested = Path(state_root)
        if not requested.is_absolute():
            raise _state_error("STATE_ROOT_UNSAFE", "state root must be absolute")
    return requested


def _physical_intended_root(requested: Path) -> Path:
    current = Path(requested.anchor)
    for part in requested.parts[1:]:
        if part in {"", "."}:
            continue
        if part == "..":
            current = current.parent
            continue
        candidate = current / part
        try:
            entry = os.lstat(candidate)
        except FileNotFoundError:
            current = candidate
            continue
        if stat.S_ISLNK(entry.st_mode):
            raise _state_error("STATE_ROOT_UNSAFE", "state root contains a symlink component")
        if not stat.S_ISDIR(entry.st_mode):
            raise _state_error("STATE_ROOT_UNSAFE", "state root contains a non-directory component")
        current = candidate
    return Path(os.path.normpath(os.fspath(requested)))


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((os.fspath(path), os.fspath(root))) == os.fspath(root)
    except ValueError:
        return False


def _git_command(root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", os.fspath(root), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _state_error("STATE_ROOT_UNSAFE", "Git worktree discovery is unavailable") from exc
    if completed.returncode != 0:
        raise _state_error("STATE_ROOT_UNSAFE", "Git worktree discovery did not complete")
    return completed.stdout


def _git_worktree_roots(root: Path) -> set[Path]:
    output = _git_command(root, "worktree", "list", "--porcelain", "-z")
    if not output.endswith(b"\0\0"):
        raise _state_error("STATE_ROOT_UNSAFE", "Git worktree discovery returned malformed output")
    worktrees: set[Path] = set()
    for record in output[:-2].split(b"\0\0"):
        fields = record.split(b"\0")
        if not fields or not fields[0].startswith(b"worktree "):
            raise _state_error("STATE_ROOT_UNSAFE", "Git worktree discovery returned malformed output")
        raw_path = fields[0][len(b"worktree ") :]
        try:
            path = Path(os.fsdecode(raw_path))
        except (TypeError, ValueError) as exc:
            raise _state_error("STATE_ROOT_UNSAFE", "Git worktree path is invalid") from exc
        if not raw_path or not path.is_absolute():
            raise _state_error("STATE_ROOT_UNSAFE", "Git worktree path is invalid")
        worktrees.add(Path(os.path.realpath(path)))
    if not worktrees:
        raise _state_error("STATE_ROOT_UNSAFE", "Git worktree discovery returned no worktrees")
    return worktrees


def _nearest_existing(path: Path) -> Path:
    current = path
    while True:
        try:
            os.lstat(current)
            return current
        except FileNotFoundError:
            if current == current.parent:
                return current
            current = current.parent


def _containing_worktree(path: Path) -> Path | None:
    current = _nearest_existing(path)
    if not stat.S_ISDIR(os.lstat(current).st_mode):
        current = current.parent
    while True:
        marker = current / ".git"
        try:
            entry = os.lstat(marker)
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(entry.st_mode) or not (
                stat.S_ISDIR(entry.st_mode) or stat.S_ISREG(entry.st_mode)
            ):
                raise _state_error("STATE_ROOT_UNSAFE", "containing Git worktree marker is unsafe")
            return Path(os.path.realpath(current))
        if current == current.parent:
            return None
        current = current.parent


def _validate_containment(state: Path, protected_roots: tuple[Path, ...]) -> None:
    protected: set[Path] = set()
    for root in protected_roots:
        try:
            physical = Path(os.path.realpath(os.fspath(root)))
        except OSError as exc:
            raise _state_error("STATE_ROOT_UNSAFE", "protected repository root is unavailable") from exc
        protected.add(physical)
        worktree = _containing_worktree(physical)
        if worktree is not None:
            protected.update(_git_worktree_roots(worktree))
    containing = _containing_worktree(state)
    if containing is not None:
        protected.add(containing)
    if any(_is_within(state, root) for root in protected):
        raise _state_error("STATE_ROOT_UNSAFE", "state root is contained by a protected Git worktree")


def _open_absolute_directory(path: Path, *, create: bool) -> int:
    current = os.open(path.anchor, _DIRECTORY_FLAGS)
    try:
        for part in path.parts[1:]:
            try:
                following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise _state_error("STATE_ROOT_UNAVAILABLE", "state root is unavailable")
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current)
                    os.fsync(current)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise _state_creation_error("state root cannot be created safely", exc) from exc
                try:
                    following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
                except OSError as exc:
                    raise _state_error("STATE_ROOT_UNSAFE", "state root was replaced during creation") from exc
            except OSError as exc:
                raise _state_error("STATE_ROOT_UNSAFE", "state root path is unsafe") from exc
            os.close(current)
            current = following
        root = os.fstat(current)
        if (
            not stat.S_ISDIR(root.st_mode)
            or root.st_uid != os.getuid()
            or stat.S_IMODE(root.st_mode) != 0o700
        ):
            raise _state_error("STATE_ROOT_UNSAFE", "state root ownership or mode is unsafe")
        return current
    except BaseException:
        os.close(current)
        raise


def _open_fixed_directory(root_descriptor: int, name: str, *, create: bool) -> int:
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=root_descriptor)
    except FileNotFoundError:
        if not create:
            raise _state_error("STATE_ROOT_UNAVAILABLE", "Growth Inbox state is incomplete")
        try:
            os.mkdir(name, mode=0o700, dir_fd=root_descriptor)
            os.fsync(root_descriptor)
        except FileExistsError:
            pass
        except OSError as exc:
            raise _state_creation_error("Growth Inbox directory cannot be created", exc) from exc
        try:
            descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=root_descriptor)
        except OSError as exc:
            raise _state_error("STATE_ROOT_UNSAFE", "Growth Inbox directory changed during creation") from exc
    except OSError as exc:
        raise _state_error("STATE_ROOT_UNSAFE", "Growth Inbox directory is unsafe") from exc
    current = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(current.st_mode)
        or current.st_uid != os.getuid()
        or stat.S_IMODE(current.st_mode) != 0o700
    ):
        os.close(descriptor)
        raise _state_error("STATE_ROOT_UNSAFE", "Growth Inbox directory ownership or mode is unsafe")
    return descriptor


def _validate_lock_file(descriptor: int) -> None:
    current = os.fstat(descriptor)
    if (
        not stat.S_ISREG(current.st_mode)
        or current.st_uid != os.getuid()
        or stat.S_IMODE(current.st_mode) != 0o600
    ):
        raise _state_error("STATE_ROOT_UNSAFE", "Growth Inbox lock file is unsafe")


def _preflight_existing_layout(root_descriptor: int, *, create: bool) -> None:
    try:
        root_entries = set(os.listdir(root_descriptor))
    except OSError as exc:
        raise _state_error("STATE_ROOT_UNSAFE", "state root cannot be enumerated safely") from exc
    unexpected = root_entries.difference(_FIXED_DIRECTORIES)
    if unexpected:
        raise _state_error("STATE_ROOT_UNSAFE", "state root contains unexpected direct entries")
    if not create and root_entries != set(_FIXED_DIRECTORIES):
        raise _state_error("STATE_ROOT_UNAVAILABLE", "Growth Inbox state is incomplete")

    directories: dict[str, int] = {}
    try:
        for name in root_entries:
            directories[name] = _open_fixed_directory(root_descriptor, name, create=False)
        if "staging" in directories and "inbox" in directories:
            if os.fstat(directories["staging"]).st_dev != os.fstat(directories["inbox"]).st_dev:
                raise _state_error("STATE_ROOT_UNSAFE", "staging and inbox must be on the same device")
        locks = directories.get("locks")
        if locks is not None:
            try:
                lock_entries = set(os.listdir(locks))
            except OSError as exc:
                raise _state_error("STATE_ROOT_UNSAFE", "Growth Inbox lock directory is unsafe") from exc
            if lock_entries.difference({"inbox.lock"}):
                raise _state_error("STATE_ROOT_UNSAFE", "Growth Inbox lock directory has unexpected entries")
            if "inbox.lock" in lock_entries:
                descriptor = -1
                try:
                    descriptor = os.open("inbox.lock", os.O_RDONLY | _NOFOLLOW, dir_fd=locks)
                    _validate_lock_file(descriptor)
                except GrowthAssessmentError:
                    raise
                except OSError as exc:
                    raise _state_error("STATE_ROOT_UNSAFE", "Growth Inbox lock file is unsafe") from exc
                finally:
                    if descriptor >= 0:
                        os.close(descriptor)
    finally:
        for descriptor in directories.values():
            os.close(descriptor)


class GrowthInbox:
    def __init__(self, repository_root: Path, state_root: Path, root_descriptor: int, filesystem: AnchoredRoot):
        self._repository_root = Path(repository_root)
        self._state_root = state_root
        self._root_descriptor = root_descriptor
        self._filesystem = filesystem
        self._publication_uncertain = False

    def _close(self) -> None:
        filesystem = getattr(self, "_filesystem", None)
        if filesystem is not None:
            filesystem.close()
            self._filesystem = None
        descriptor = getattr(self, "_root_descriptor", -1)
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
            self._root_descriptor = -1

    def __del__(self) -> None:
        self._close()

    @classmethod
    def _open(
        cls,
        repository_root: Path,
        source_root: Path | None,
        state_root: Path | None,
        *,
        create: bool,
    ) -> "GrowthInbox":
        requested = _resolve_state_root(state_root)
        physical = _physical_intended_root(requested)
        protected = (Path(repository_root),) if source_root is None else (Path(repository_root), Path(source_root))
        _validate_containment(physical, protected)
        root_descriptor = _open_absolute_directory(physical, create=create)
        filesystem: AnchoredRoot | None = None
        instance: GrowthInbox | None = None
        try:
            _preflight_existing_layout(root_descriptor, create=create)
            directories: dict[str, int] = {}
            try:
                for name in _FIXED_DIRECTORIES:
                    directories[name] = _open_fixed_directory(root_descriptor, name, create=create)
                if os.fstat(directories["staging"]).st_dev != os.fstat(directories["inbox"]).st_dev:
                    raise _state_error("STATE_ROOT_UNSAFE", "staging and inbox must be on the same device")
            finally:
                for descriptor in directories.values():
                    os.close(descriptor)
            filesystem = AnchoredRoot(physical)
            anchored = os.fstat(filesystem._descriptor)
            opened = os.fstat(root_descriptor)
            if (anchored.st_dev, anchored.st_ino) != (opened.st_dev, opened.st_ino):
                raise _state_error("STATE_ROOT_UNSAFE", "state root changed while it was opened")
            instance = cls(repository_root, physical, root_descriptor, filesystem)
            instance._open_lock(create=create, writable=create, close_immediately=True)
            return instance
        except BaseException:
            if instance is not None:
                instance._close()
            else:
                if filesystem is not None:
                    filesystem.close()
                os.close(root_descriptor)
            raise

    @classmethod
    def open_for_record(
        cls,
        repository_root: Path,
        source_root: Path,
        state_root: Path | None,
    ) -> "GrowthInbox":
        return cls._open(repository_root, source_root, state_root, create=True)

    @classmethod
    def open_read_only(cls, repository_root: Path, state_root: Path | None) -> "GrowthInbox":
        return cls._open(repository_root, None, state_root, create=False)

    def _directory(self, name: str) -> int:
        return _open_fixed_directory(self._root_descriptor, name, create=False)

    def _open_lock(self, *, create: bool, writable: bool, close_immediately: bool = False) -> int:
        locks = self._directory("locks")
        flags = (os.O_RDWR if writable else os.O_RDONLY) | _NOFOLLOW
        if create:
            flags |= os.O_CREAT
        descriptor = -1
        try:
            descriptor = os.open("inbox.lock", flags, 0o600, dir_fd=locks)
            _validate_lock_file(descriptor)
        except FileNotFoundError as exc:
            if descriptor >= 0:
                os.close(descriptor)
                descriptor = -1
            raise _state_error("STATE_ROOT_UNAVAILABLE", "Growth Inbox lock file is unavailable") from exc
        except GrowthAssessmentError:
            if descriptor >= 0:
                os.close(descriptor)
                descriptor = -1
            raise
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
                descriptor = -1
            raise _state_error("STATE_ROOT_UNSAFE", "Growth Inbox lock file is unsafe") from exc
        finally:
            if descriptor >= 0 and close_immediately:
                os.close(descriptor)
                descriptor = -1
            os.close(locks)
        return descriptor

    @contextmanager
    def _lock(self, *, exclusive: bool) -> Iterator[None]:
        descriptor = self._open_lock(create=False, writable=exclusive)
        operation = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
        try:
            try:
                fcntl.flock(descriptor, operation)
            except BlockingIOError as exc:
                raise _state_error("INBOX_LOCKED", "Growth Inbox lock is busy") from exc
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _read_receipt_bytes(self, name: str) -> bytes | None:
        inbox = self._directory("inbox")
        descriptor = -1
        try:
            try:
                named = os.stat(name, dir_fd=inbox, follow_symlinks=False)
            except FileNotFoundError:
                return None
            if (
                not stat.S_ISREG(named.st_mode)
                or named.st_uid != os.getuid()
                or stat.S_IMODE(named.st_mode) != 0o600
                or named.st_size > _RECEIPT_LIMIT
            ):
                raise _state_error("RECEIPT_UNSAFE", "receipt entry is unsafe")
            try:
                descriptor = os.open(name, os.O_RDONLY | _NOFOLLOW, dir_fd=inbox)
            except OSError as exc:
                raise _state_error("RECEIPT_UNSAFE", "receipt entry cannot be opened safely") from exc
            opened = os.fstat(descriptor)
            if (
                (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
                or not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.getuid()
                or stat.S_IMODE(opened.st_mode) != 0o600
                or opened.st_size > _RECEIPT_LIMIT
            ):
                raise _state_error("RECEIPT_UNSAFE", "receipt entry changed while opening")
            chunks: list[bytes] = []
            remaining = _RECEIPT_LIMIT + 1
            while remaining:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) > _RECEIPT_LIMIT:
                raise _state_error("RECEIPT_UNSAFE", "receipt entry exceeds the encoded-size limit")
            return raw
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(inbox)

    def _validated_receipt(self, name: str, raw: bytes) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _state_error("RECEIPT_CORRUPT", "receipt JSON is invalid") from exc
        if not isinstance(value, dict):
            raise _state_error("RECEIPT_CORRUPT", "receipt root is invalid")
        try:
            receipt = validate_growth_receipt(self._repository_root, value)
        except GrowthAssessmentError as exc:
            raise _state_error("RECEIPT_CORRUPT", "receipt identities or schema are invalid") from exc
        if receipt["status"] != "RECORDED":
            raise _state_error("RECEIPT_CORRUPT", "persisted receipt status is invalid")
        if receipt["assessmentKey"].split(":", 1)[1] + ".json" != name:
            raise _state_error("RECEIPT_CORRUPT", "receipt filename does not match its key")
        if raw != canonical_json_bytes(receipt) + b"\n":
            raise _state_error("RECEIPT_CORRUPT", "receipt bytes are not canonical")
        return receipt

    def record(self, request: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_growth_assessment_request(self._repository_root, request)
        if self._publication_uncertain:
            raise _state_error("STATE_ROOT_UNSAFE", "a prior receipt publication is not durability-confirmed")
        expected = build_growth_receipt(normalized)
        expected_bytes = canonical_json_bytes(expected) + b"\n"
        if len(expected_bytes) > _RECEIPT_LIMIT:
            raise _state_error("RECEIPT_UNSAFE", "encoded receipt exceeds the size limit")
        name = expected["assessmentKey"].split(":", 1)[1] + ".json"
        with self._lock(exclusive=True):
            raw = self._read_receipt_bytes(name)
            if raw is not None:
                current = self._validated_receipt(name, raw)
                if raw != expected_bytes:
                    raise _state_error("ASSESSMENT_KEY_CONFLICT", "assessment key already has another receipt")
                duplicate = copy.deepcopy(current)
                duplicate["status"] = "DUPLICATE"
                return duplicate
            try:
                self._filesystem.publish_bytes_no_replace("staging", f"inbox/{name}", expected_bytes, mode=0o600)
            except AnchoredPathError as exc:
                self._publication_uncertain = True
                raise _state_error("STATE_ROOT_UNSAFE", "receipt publication failed safely") from exc
            return copy.deepcopy(expected)

    def receipt(self, assessment_id: str) -> dict[str, Any]:
        if not isinstance(assessment_id, str) or _ASSESSMENT_ID.fullmatch(assessment_id) is None:
            raise _state_error("GROWTH_ARGUMENT_INVALID", "assessment ID is invalid")
        with self._lock(exclusive=False):
            inbox = self._directory("inbox")
            try:
                names = os.listdir(inbox)
            except OSError as exc:
                raise _state_error("STATE_ROOT_UNSAFE", "Inbox enumeration failed") from exc
            finally:
                os.close(inbox)
            matches: list[dict[str, Any]] = []
            for name in names:
                if _RECEIPT_NAME.fullmatch(name) is None:
                    continue
                raw = self._read_receipt_bytes(name)
                if raw is None:
                    continue
                current = self._validated_receipt(name, raw)
                if current["assessmentId"] == assessment_id:
                    matches.append(current)
            if len(matches) != 1:
                raise _state_error("RECEIPT_NOT_FOUND", "exactly one matching receipt was not found")
            return copy.deepcopy(matches[0])

    @staticmethod
    def _entry_digest(name: str) -> str:
        return "sha256:" + sha256_bytes(b"growth-inbox-entry/v1\0" + os.fsencode(name))

    @staticmethod
    def _invalid_record(name: str, code: str) -> dict[str, str]:
        return {
            "entryNameDigest": GrowthInbox._entry_digest(name),
            "errorCode": code,
            "disposition": "INVALID_RECEIPT",
        }

    @staticmethod
    def _scan_record(receipt: dict[str, Any]) -> dict[str, Any]:
        assessment = receipt["assessment"]
        visibility_order = {"PRIVATE": 0, "PROJECT": 1, "SHARED": 2, "PUBLIC": 3}
        visibility = "NONE"
        if assessment["evidence"]:
            visibility = min(
                (item["visibility"] for item in assessment["evidence"]),
                key=visibility_order.__getitem__,
            )
        signal = assessment["verdict"] == "SIGNAL"
        return {
            "assessmentKey": receipt["assessmentKey"],
            "assessmentId": receipt["assessmentId"],
            "requestDigest": receipt["requestDigest"],
            "projectId": assessment["source"]["projectId"],
            "sourceKind": assessment["source"]["sourceKind"],
            "riskLevel": assessment["riskLevel"],
            "trigger": assessment["trigger"],
            "verdict": assessment["verdict"],
            "visibilityCeiling": visibility,
            "capabilityHints": copy.deepcopy(assessment["capabilityHints"]),
            "disposition": "HUMAN_TRIAGE_REQUIRED" if signal else "NO_ACTION",
        }

    def _bounded_inbox_names(self) -> list[str]:
        inbox = self._directory("inbox")
        names: list[str] = []
        try:
            try:
                with os.scandir(inbox) as entries:
                    for entry in entries:
                        if len(names) == _SCAN_LIMIT:
                            raise _state_error("SCAN_LIMIT_EXCEEDED", "Inbox entry limit exceeded")
                        names.append(entry.name)
            except GrowthAssessmentError:
                raise
            except OSError as exc:
                raise _state_error("STATE_ROOT_UNSAFE", "Inbox enumeration failed") from exc
            return names
        finally:
            os.close(inbox)

    def scan(self, *, as_of: str) -> dict[str, Any]:
        normalized_as_of = _utc_rfc3339(as_of)
        observed_at = _rfc3339_order_key(normalized_as_of)
        with self._lock(exclusive=False):
            names = self._bounded_inbox_names()
            records: list[dict[str, Any]] = []
            signal = 0
            no_signal = 0
            for name in names:
                if _RECEIPT_NAME.fullmatch(name) is None:
                    records.append(self._invalid_record(name, "RECEIPT_UNSAFE"))
                    continue
                try:
                    raw = self._read_receipt_bytes(name)
                    if raw is None:
                        raise _state_error("RECEIPT_UNSAFE", "receipt disappeared during scan")
                    receipt = self._validated_receipt(name, raw)
                except GrowthAssessmentError as exc:
                    code = "RECEIPT_UNSAFE" if exc.code == "RECEIPT_UNSAFE" else "RECEIPT_CORRUPT"
                    records.append(self._invalid_record(name, code))
                    continue
                if _rfc3339_order_key(receipt["assessment"]["assessedAt"]) > observed_at:
                    raise _state_error("TIMESTAMP_INVALID", "scan observation predates a valid receipt")
                record = self._scan_record(receipt)
                records.append(record)
                if record["verdict"] == "SIGNAL":
                    signal += 1
                else:
                    no_signal += 1
            records.sort(
                key=lambda record: (
                    record["disposition"],
                    record.get("assessmentKey", record.get("entryNameDigest", "")),
                    record.get("assessmentId", ""),
                )
            )
            invalid = len(records) - signal - no_signal
            report = {
                "schemaVersion": "growth-scan-report/v1",
                "policyVersion": GROWTH_POLICY_VERSION,
                "asOf": normalized_as_of,
                "stateRootIdentity": "sha256:"
                + sha256_bytes(b"growth-state-root/v1\0" + os.fsencode(str(self._state_root))),
                "records": records,
                "counts": {
                    "totalEntries": len(records),
                    "validRecords": signal + no_signal,
                    "invalidRecords": invalid,
                    "signal": signal,
                    "noSignal": no_signal,
                    "humanTriageRequired": signal,
                    "noAction": no_signal,
                },
                "gate": "PASS" if invalid == 0 else "FAIL",
            }
            try:
                SchemaStore(self._repository_root).validate(_SCAN_SCHEMA, report)
            except (SchemaValidationError, FileNotFoundError) as exc:
                raise _state_error("RECEIPT_CORRUPT", "scan report failed schema validation") from exc
            return report
