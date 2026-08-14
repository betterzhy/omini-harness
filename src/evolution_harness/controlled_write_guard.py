from __future__ import annotations

import copy
import ctypes
import hashlib
import os
import signal
import stat
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .controlled_coordinator_inputs import ControlledCoordinationError
from .coordinator_state import CoordinatorStateStore


_SANDBOX_EXEC_PATH = "/usr/bin/sandbox-exec"
_SANDBOX_EXEC_SHA256 = (
    "8857d087219f0f39d3e3c163e5d0a0aed690cc22f34b50c7eee3d74f93e69688"
)
_GIT_PATH = "/usr/bin/git"
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


class GuardedCommandResult(subprocess.CompletedProcess[bytes]):
    beforeInventory: dict[str, object]
    afterInventory: dict[str, object]
    observedPaths: list[str]
    ephemeralPathsRemoved: bool

    def __init__(
        self,
        args: list[str],
        returncode: int,
        stdout: bytes,
        stderr: bytes,
        *,
        before_inventory: dict[str, object],
        after_inventory: dict[str, object],
        observed_paths: list[str],
        ephemeral_paths_removed: bool,
    ) -> None:
        super().__init__(args, returncode, stdout, stderr)
        self.beforeInventory = before_inventory
        self.afterInventory = after_inventory
        self.observedPaths = observed_paths
        self.ephemeralPathsRemoved = ephemeral_paths_removed


@dataclass
class _AnchoredTarget:
    relative: str
    absolute: Path
    descriptor: int | None
    identity: tuple[int, int, int] | None
    target_type: str
    is_ephemeral: bool


def _error(
    code: str, message: str, *, observed_paths: list[str] | None = None
) -> ControlledCoordinationError:
    error = ControlledCoordinationError(code, message)
    if observed_paths is not None:
        error.observedPaths = observed_paths
    return error


def _physical_identity(current: os.stat_result) -> tuple[int, int, int]:
    return current.st_dev, current.st_ino, stat.S_IFMT(current.st_mode)


def _canonical_absolute(path: Path, label: str) -> Path:
    raw = os.fspath(path)
    if not raw or "\x00" in raw or not raw.startswith("/"):
        raise _error("UNSAFE_WRITE_TARGET", f"{label} must be an absolute path")
    normalized = os.path.normpath(raw)
    if normalized != raw:
        raise _error("UNSAFE_WRITE_TARGET", f"{label} must be canonical")
    return Path(normalized)


def _canonical_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise _error("UNSAFE_WRITE_TARGET", f"{label} must be a relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise _error("UNSAFE_WRITE_TARGET", f"{label} must be canonical and relative")
    if path.parts[0] == ".git":
        raise _error("UNSAFE_WRITE_TARGET", "Git administration paths are never writable")
    return value


def _open_absolute_directory_no_follow(path: Path) -> tuple[int, os.stat_result]:
    current = os.open("/", _DIRECTORY_FLAGS)
    try:
        for part in path.parts[1:]:
            following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
            os.close(current)
            current = following
        opened = os.fstat(current)
        if not stat.S_ISDIR(opened.st_mode):
            raise OSError("path is not a directory")
        return current, opened
    except BaseException:
        os.close(current)
        raise


def _open_target_no_follow(
    lane_descriptor: int,
    lane_root: Path,
    relative: str,
    *,
    is_ephemeral: bool,
) -> _AnchoredTarget:
    parts = PurePosixPath(relative).parts
    current = os.dup(lane_descriptor)
    final_descriptor: int | None = None
    try:
        for index, part in enumerate(parts):
            final = index == len(parts) - 1
            flags = _READ_FLAGS if final else _DIRECTORY_FLAGS
            try:
                following = os.open(part, flags, dir_fd=current)
            except FileNotFoundError:
                if not final:
                    raise _error(
                        "UNSAFE_WRITE_TARGET",
                        f"creation requires an existing anchored parent: {relative}",
                    )
                return _AnchoredTarget(
                    relative=relative,
                    absolute=lane_root / relative,
                    descriptor=None,
                    identity=None,
                    target_type="MISSING",
                    is_ephemeral=is_ephemeral,
                )
            except OSError as exc:
                raise _error(
                    "UNSAFE_WRITE_TARGET",
                    f"write target contains a symlink or unsafe component: {relative}",
                ) from exc
            if final:
                final_descriptor = following
                following = -1
                observed = os.fstat(final_descriptor)
                target_type = (
                    "DIRECTORY"
                    if stat.S_ISDIR(observed.st_mode)
                    else "REGULAR"
                    if stat.S_ISREG(observed.st_mode)
                    else "OTHER"
                )
                if target_type == "OTHER":
                    raise _error(
                        "UNSAFE_WRITE_TARGET",
                        f"write target must be a regular file or directory: {relative}",
                    )
                return _AnchoredTarget(
                    relative=relative,
                    absolute=lane_root / relative,
                    descriptor=final_descriptor,
                    identity=_physical_identity(observed),
                    target_type=target_type,
                    is_ephemeral=is_ephemeral,
                )
            os.close(current)
            current = following
        raise AssertionError("empty write target")
    finally:
        os.close(current)


def _close_targets(targets: list[_AnchoredTarget]) -> None:
    for target in targets:
        if target.descriptor is not None:
            os.close(target.descriptor)
            target.descriptor = None


def _path_is_within(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _validate_declared_sets(
    lane_descriptor: int,
    lane_root: Path,
    durable_lease: dict[str, Any],
) -> tuple[list[_AnchoredTarget], list[str], list[str]]:
    footprint = durable_lease.get("fullFootprint")
    if not isinstance(footprint, dict):
        raise _error("LEASE_WRITESET_INVALID", "lease has no durable WriteSet footprint")
    exact_raw = footprint.get("exactWriteSet")
    ephemeral_raw = footprint.get("ephemeralWriteSet")
    if not isinstance(exact_raw, list) or not isinstance(ephemeral_raw, list):
        raise _error("LEASE_WRITESET_INVALID", "lease WriteSets must be lists")
    exact = sorted(
        {_canonical_relative(item, "exactWriteSet") for item in exact_raw}
    )
    ephemeral = sorted(
        {_canonical_relative(item, "ephemeralWriteSet") for item in ephemeral_raw}
    )
    if len(exact) != len(exact_raw) or len(ephemeral) != len(ephemeral_raw):
        raise _error("LEASE_WRITESET_INVALID", "WriteSet aliases or duplicates are denied")
    for left in exact:
        for right in ephemeral:
            if _path_is_within(left, right) or _path_is_within(right, left):
                raise _error(
                    "UNSAFE_EPHEMERAL_WRITESET",
                    "ephemeral and exact WriteSets must not alias or overlap",
                )
    if durable_lease.get("candidateIdentity") is not None and ephemeral:
        raise _error(
            "UNSAFE_EPHEMERAL_WRITESET",
            "ephemeral paths must be absent from a fixed candidate",
        )

    targets: list[_AnchoredTarget] = []
    identities: dict[tuple[int, int, int], str] = {}
    try:
        for is_ephemeral, paths in ((False, exact), (True, ephemeral)):
            for relative in paths:
                target = _open_target_no_follow(
                    lane_descriptor,
                    lane_root,
                    relative,
                    is_ephemeral=is_ephemeral,
                )
                if target.identity is not None:
                    alias = identities.get(target.identity)
                    if alias is not None:
                        raise _error(
                            "UNSAFE_WRITE_TARGET",
                            f"physical WriteSet alias denied: {alias}, {relative}",
                        )
                    identities[target.identity] = relative
                targets.append(target)
        _validate_ephemeral_paths(lane_root, ephemeral)
        return targets, exact, ephemeral
    except BaseException:
        _close_targets(targets)
        raise


def _run_git(lane_root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            [_GIT_PATH, "-C", str(lane_root), *args],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise _error("LANE_INVENTORY_UNAVAILABLE", "Git lane inventory failed") from exc


def _validate_ephemeral_paths(lane_root: Path, ephemeral: list[str]) -> None:
    for relative in ephemeral:
        ignored = any(
            subprocess.run(
                [_GIT_PATH, "-C", str(lane_root), "check-ignore", "-q", "--", candidate],
                check=False,
                capture_output=True,
            ).returncode
            == 0
            for candidate in (relative, f"{relative}/.guard-ignore-probe")
        )
        if not ignored:
            raise _error(
                "UNSAFE_EPHEMERAL_WRITESET",
                f"ephemeral path is not Git-ignored: {relative}",
            )
        tracked = subprocess.run(
            [_GIT_PATH, "-C", str(lane_root), "ls-files", "--error-unmatch", "--", relative],
            check=False,
            capture_output=True,
        )
        if tracked.returncode == 0:
            raise _error(
                "UNSAFE_EPHEMERAL_WRITESET",
                f"ephemeral path is already tracked: {relative}",
            )


def _parse_status(raw: bytes) -> tuple[list[str], list[str], list[str]]:
    fields = raw.split(b"\0")
    paths: list[str] = []
    tracked: list[str] = []
    untracked: list[str] = []
    index = 0
    while index < len(fields) and fields[index]:
        entry = fields[index]
        index += 1
        if len(entry) < 4 or entry[2:3] != b" ":
            raise _error("LANE_INVENTORY_UNAVAILABLE", "malformed Git status entry")
        status_code = entry[:2]
        path = os.fsdecode(entry[3:])
        if status_code[:1] in {b"R", b"C"} or status_code[1:2] in {b"R", b"C"}:
            if index >= len(fields) or not fields[index]:
                raise _error("LANE_INVENTORY_UNAVAILABLE", "malformed Git rename entry")
            path = os.fsdecode(fields[index])
            index += 1
        normalized = _canonical_relative(path, "Git inventory path")
        paths.append(normalized)
        if status_code == b"??":
            untracked.append(normalized)
        else:
            tracked.append(normalized)
    return sorted(set(paths)), sorted(set(tracked)), sorted(set(untracked))


def _inventory(lane_descriptor: int, lane_root: Path) -> dict[str, object]:
    status_result = _run_git(
        lane_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--ignore-submodules=none",
    )
    paths, tracked, untracked = _parse_status(status_result.stdout)
    entries: list[dict[str, object]] = []
    symlinks: list[str] = []
    for relative in paths:
        current = os.dup(lane_descriptor)
        identity: dict[str, object]
        try:
            parts = PurePosixPath(relative).parts
            for index, part in enumerate(parts):
                final = index == len(parts) - 1
                flags = _READ_FLAGS if final else _DIRECTORY_FLAGS
                try:
                    following = os.open(part, flags, dir_fd=current)
                except FileNotFoundError:
                    identity = {
                        "type": "ABSENT",
                        "device": None,
                        "inode": None,
                        "sha256": None,
                    }
                    break
                except OSError:
                    observed = os.stat(part, dir_fd=current, follow_symlinks=False)
                    if stat.S_ISLNK(observed.st_mode):
                        symlink_path = PurePosixPath(*parts[: index + 1]).as_posix()
                        symlinks.append(symlink_path)
                        identity = {
                            "type": "SYMLINK",
                            "device": observed.st_dev,
                            "inode": observed.st_ino,
                            "sha256": None,
                        }
                        break
                    raise
                os.close(current)
                current = following
                if final:
                    observed = os.fstat(current)
                    digest = None
                    if stat.S_ISREG(observed.st_mode):
                        hasher = hashlib.sha256()
                        while True:
                            chunk = os.read(current, 1024 * 1024)
                            if not chunk:
                                break
                            hasher.update(chunk)
                        digest = hasher.hexdigest()
                    identity = {
                        "type": (
                            "DIRECTORY"
                            if stat.S_ISDIR(observed.st_mode)
                            else "REGULAR"
                            if stat.S_ISREG(observed.st_mode)
                            else "OTHER"
                        ),
                        "device": observed.st_dev,
                        "inode": observed.st_ino,
                        "sha256": digest,
                    }
        finally:
            os.close(current)
        entries.append({"path": relative, **identity})
    return {
        "paths": paths,
        "trackedPaths": tracked,
        "untrackedPaths": untracked,
        "symlinkPaths": sorted(set(symlinks)),
        "entries": entries,
    }


def _persistent_breaches(paths: list[str], exact: list[str], ephemeral: list[str]) -> list[str]:
    breaches = []
    for path in paths:
        if any(_path_is_within(path, allowed) for allowed in exact):
            continue
        if any(_path_is_within(path, temporary) for temporary in ephemeral):
            continue
        breaches.append(path)
    return sorted(breaches)


def _revalidate_targets(targets: list[_AnchoredTarget]) -> None:
    for target in targets:
        if target.identity is None:
            continue
        try:
            named = os.stat(target.absolute, follow_symlinks=False)
        except OSError as exc:
            raise _error(
                "WRITE_TARGET_IDENTITY_CHANGED",
                f"anchored write target disappeared: {target.relative}",
            ) from exc
        if stat.S_ISLNK(named.st_mode) or _physical_identity(named) != target.identity:
            raise _error(
                "WRITE_TARGET_IDENTITY_CHANGED",
                f"anchored write target changed during execution: {target.relative}",
            )


def _sandbox_literal(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _sandbox_profile(targets: list[_AnchoredTarget]) -> str:
    write_rules = [
        f"(literal {_sandbox_literal('/dev/null')})",
        f"(literal {_sandbox_literal('/dev/tty')})",
    ]
    for target in targets:
        write_rules.append(f"(literal {_sandbox_literal(str(target.absolute))})")
        if target.target_type == "DIRECTORY" or target.is_ephemeral:
            write_rules.append(f"(subpath {_sandbox_literal(str(target.absolute))})")
    return " ".join(
        [
            "(version 1)",
            "(deny default)",
            "(allow file-read*)",
            "(allow process*)",
            "(allow sysctl-read)",
            "(allow mach-lookup)",
            "(allow file-write* " + " ".join(write_rules) + ")",
        ]
    )


def _validate_sandbox_exec() -> None:
    descriptor = -1
    try:
        named = os.stat(_SANDBOX_EXEC_PATH, follow_symlinks=False)
        descriptor = os.open(_SANDBOX_EXEC_PATH, _READ_FLAGS)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != 0
            or opened.st_gid != 0
            or stat.S_IMODE(opened.st_mode) & 0o022
            or _physical_identity(named) != _physical_identity(opened)
        ):
            raise OSError("sandbox-exec identity or ownership is unsafe")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        if digest.hexdigest() != _SANDBOX_EXEC_SHA256:
            raise OSError("sandbox-exec digest changed")
    except (OSError, ValueError) as exc:
        raise _error(
            "PROCESS_SANDBOX_UNAVAILABLE",
            "absolute /usr/bin/sandbox-exec is missing, replaced, or unsafe",
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _load_child_pid_function():
    try:
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        function = library.proc_listchildpids
        function.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        function.restype = ctypes.c_int
        return function
    except (AttributeError, OSError) as exc:
        raise _error(
            "PROCESS_SANDBOX_UNAVAILABLE",
            "the host cannot enumerate the complete sandbox process tree",
        ) from exc


class _DescendantTracker:
    def __init__(self, root_pid: int, function):
        self._function = function
        self._root_pid = root_pid
        self._known = {root_pid}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._track, daemon=True)

    def _children(self, pid: int) -> list[int]:
        values = (ctypes.c_int * 4096)()
        count = self._function(pid, ctypes.byref(values), ctypes.sizeof(values))
        if count < 0:
            return []
        return [values[index] for index in range(min(count, len(values))) if values[index] > 0]

    def _track(self) -> None:
        while not self._stop.is_set():
            for pid in tuple(self._known):
                self._known.update(self._children(pid))
            self._stop.wait(0.001)

    def start(self) -> None:
        self._thread.start()

    def stop_and_reap(self) -> None:
        for _ in range(10):
            for pid in tuple(self._known):
                self._known.update(self._children(pid))
            time.sleep(0.001)
        self._stop.set()
        self._thread.join(timeout=1)
        descendants = sorted(self._known - {self._root_pid})
        for pid in descendants:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError as exc:
                raise _error(
                    "PROCESS_SANDBOX_UNAVAILABLE",
                    "a sandbox descendant could not be terminated",
                ) from exc
        deadline = time.monotonic() + 5
        remaining = set(descendants)
        while remaining and time.monotonic() < deadline:
            for pid in tuple(remaining):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    remaining.remove(pid)
            if remaining:
                time.sleep(0.01)
        if remaining:
            raise _error(
                "PROCESS_SANDBOX_UNAVAILABLE",
                "the complete sandbox process tree did not become quiescent",
            )


def _run_sandboxed(
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    profile: str,
) -> subprocess.CompletedProcess[bytes]:
    command = [_SANDBOX_EXEC_PATH, "-p", profile, *argv]
    child_pid_function = _load_child_pid_function()
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise _error(
            "PROCESS_SANDBOX_UNAVAILABLE", "sandboxed command could not start"
        ) from exc
    tracker = _DescendantTracker(process.pid, child_pid_function)
    tracker.start()
    try:
        stdout, stderr = process.communicate()
    finally:
        tracker.stop_and_reap()
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def _current_durable_lease(
    journal: dict[str, Any] | None, presented: dict[str, Any]
) -> dict[str, Any]:
    if journal is None:
        raise _error("COORDINATOR_LEASE_NOT_FOUND", "guard lease is not durable")
    if journal.get("recoveryState") != "CLEAR":
        raise _error(
            "COORDINATOR_RECOVERY_REQUIRED",
            "project recovery must close before a guarded command",
        )
    lease_id = presented.get("leaseId")
    durable = next(
        (item for item in journal.get("leases", []) if item.get("leaseId") == lease_id),
        None,
    )
    if durable is None:
        raise _error("COORDINATOR_LEASE_NOT_FOUND", "guard lease is not durable")
    if presented.get("attemptId") != durable.get("attemptId"):
        raise _error("LEASE_ATTEMPT_MISMATCH", "guard attempt does not own the lease")
    if presented.get("fencingToken") != durable.get("fencingToken"):
        raise _error("STALE_FENCING_TOKEN", "guard fencing token is not current")
    if (
        presented.get("state") != "ACTIVE"
        or durable.get("state") != "ACTIVE"
        or presented.get("released") is not False
        or durable.get("released") is not False
        or durable.get("recoveryStatus") != "CLEAR"
    ):
        raise _error("LEASE_NOT_ACTIVE", "guard requires one active retained lease")
    for field in ("projectExecutionKey", "laneRoot", "fullFootprint"):
        if presented.get(field) != durable.get(field):
            raise _error("STALE_LEASE_BINDING", f"guard lease changed at {field}")
    return copy.deepcopy(durable)


def run_guarded_command(
    lease: dict[str, object],
    lane_root: Path,
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[bytes]:
    """Run one fenced foreground command inside a physical WriteSet sandbox."""
    if not isinstance(lease, dict):
        raise _error("COORDINATOR_LEASE_NOT_FOUND", "guard lease must be an object")
    if "fencingToken" not in lease or lease.get("fencingToken") is None:
        raise _error("MISSING_FENCING_TOKEN", "guard requires a fencing token")
    if not isinstance(argv, list) or not argv or any(
        not isinstance(item, str) or not item or "\x00" in item for item in argv
    ):
        raise _error("GUARDED_COMMAND_INVALID", "argv must be a nonempty string list")
    if not isinstance(environment, dict) or any(
        not isinstance(key, str)
        or not key
        or "=" in key
        or "\x00" in key
        or not isinstance(value, str)
        or "\x00" in value
        for key, value in environment.items()
    ):
        raise _error("GUARDED_COMMAND_INVALID", "environment must contain safe strings")

    requested_lane = _canonical_absolute(Path(lane_root), "lane root")
    requested_cwd = _canonical_absolute(Path(cwd), "cwd")
    try:
        requested_cwd.relative_to(requested_lane)
    except ValueError as exc:
        raise _error("GUARDED_COMMAND_INVALID", "cwd must stay inside the lane") from exc

    _validate_sandbox_exec()
    identity = {"projectExecutionKey": lease.get("projectExecutionKey")}
    with CoordinatorStateStore.open(identity) as store:
        with store.exclusive_project_lock():
            durable = _current_durable_lease(store.read_journal(), lease)
            if durable["laneRoot"] != str(requested_lane):
                raise _error("STALE_LEASE_BINDING", "lane root is not lease-owned")
            lane_descriptor = -1
            targets: list[_AnchoredTarget] = []
            try:
                lane_descriptor, opened = _open_absolute_directory_no_follow(requested_lane)
                expected = durable.get("lanePhysicalIdentity")
                if not isinstance(expected, dict) or (
                    opened.st_dev,
                    opened.st_ino,
                    "DIRECTORY",
                ) != (
                    expected.get("device"),
                    expected.get("inode"),
                    expected.get("type"),
                ):
                    raise _error(
                        "LANE_ROOT_IDENTITY_CHANGED",
                        "guarded lane physical identity changed",
                    )
                cwd_descriptor, _ = _open_absolute_directory_no_follow(requested_cwd)
                os.close(cwd_descriptor)
                targets, exact, ephemeral = _validate_declared_sets(
                    lane_descriptor, requested_lane, durable
                )
                before = _inventory(lane_descriptor, requested_lane)
                before_breaches = _persistent_breaches(
                    before["paths"], exact, ephemeral
                )
                if before_breaches:
                    raise _error(
                        "WRITESET_BREACH",
                        "lane already contains persistent paths outside exactWriteSet",
                        observed_paths=before_breaches,
                    )
                result = _run_sandboxed(
                    argv,
                    cwd=requested_cwd,
                    environment=copy.deepcopy(environment),
                    profile=_sandbox_profile(targets),
                )
                after = _inventory(lane_descriptor, requested_lane)
                _revalidate_targets(targets)
                after_breaches = _persistent_breaches(after["paths"], exact, ephemeral)
                if after_breaches:
                    raise _error(
                        "WRITESET_BREACH",
                        "guarded command produced persistent paths outside exactWriteSet",
                        observed_paths=after_breaches,
                    )
                remaining_ephemeral = sorted(
                    path
                    for path in after["paths"]
                    if any(_path_is_within(path, item) for item in ephemeral)
                )
                if remaining_ephemeral:
                    raise _error(
                        "EPHEMERAL_PATH_NOT_REMOVED",
                        "guarded command left ephemeral paths before closure",
                        observed_paths=remaining_ephemeral,
                    )
                before_entries = {
                    item["path"]: item for item in before["entries"]
                }
                observed_paths = sorted(
                    item["path"]
                    for item in after["entries"]
                    if before_entries.get(item["path"]) != item
                )
                return GuardedCommandResult(
                    result.args,
                    result.returncode,
                    result.stdout,
                    result.stderr,
                    before_inventory=before,
                    after_inventory=after,
                    observed_paths=observed_paths,
                    ephemeral_paths_removed=True,
                )
            except OSError as exc:
                raise _error(
                    "UNSAFE_WRITE_TARGET", "guarded path could not be opened no-follow"
                ) from exc
            finally:
                _close_targets(targets)
                if lane_descriptor >= 0:
                    os.close(lane_descriptor)
