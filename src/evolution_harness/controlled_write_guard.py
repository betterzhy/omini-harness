from __future__ import annotations

import copy
import hashlib
import os
import stat
import subprocess
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .controlled_coordinator_inputs import ControlledCoordinationError
from .coordinator_state import CoordinatorStateStore
from .hashing import canonical_json_bytes


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
_SEALED_GIT_ENVIRONMENT = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "HOME": "/var/empty",
    "LANG": "C",
    "LC_ALL": "C",
    "GIT_PAGER": "",
    "PAGER": "",
    "PATH": "/usr/bin:/bin",
    "XDG_CONFIG_HOME": "/var/empty",
}
_GIT_DISABLED_EXECUTABLE_EXTENSIONS = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "submodule.recurse=false",
    "-c",
    "status.submoduleSummary=false",
    "-c",
    "protocol.allow=never",
    "--no-pager",
)


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
class _AnchoredComponent:
    relative: str
    descriptor: int
    identity: tuple[int, int, int]


@dataclass
class _AnchoredTarget:
    relative: str
    absolute: Path
    descriptor: int | None
    identity: tuple[int, int, int] | None
    target_type: str
    is_ephemeral: bool
    ancestors: list[_AnchoredComponent]


@dataclass
class _GitBoundary:
    lane_root: Path
    lane_descriptor: int
    lane_identity: tuple[int, int, int]
    dot_git_descriptor: int
    dot_git_identity: tuple[int, int, int]
    dot_git_type: str
    dot_git_contents: bytes | None
    admin_root: Path
    admin_descriptor: int
    admin_identity: tuple[int, int, int]


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
    ancestors = [
        _AnchoredComponent(
            relative="",
            descriptor=os.dup(current),
            identity=_physical_identity(os.fstat(current)),
        )
    ]
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
                    ancestors=ancestors,
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
                    ancestors=ancestors,
                )
            component_relative = PurePosixPath(*parts[: index + 1]).as_posix()
            ancestors.append(
                _AnchoredComponent(
                    relative=component_relative,
                    descriptor=os.dup(following),
                    identity=_physical_identity(os.fstat(following)),
                )
            )
            os.close(current)
            current = following
        raise AssertionError("empty write target")
    except BaseException:
        if final_descriptor is not None:
            os.close(final_descriptor)
        for component in ancestors:
            os.close(component.descriptor)
        raise
    finally:
        os.close(current)


def _close_targets(targets: list[_AnchoredTarget]) -> None:
    for target in targets:
        if target.descriptor is not None:
            os.close(target.descriptor)
            target.descriptor = None
        for component in target.ancestors:
            os.close(component.descriptor)
        target.ancestors = []


def _path_is_within(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _validate_declared_sets(
    lane_descriptor: int,
    lane_root: Path,
    git_boundary: _GitBoundary,
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
        _validate_ephemeral_paths(git_boundary, ephemeral)
        return targets, exact, ephemeral
    except BaseException:
        _close_targets(targets)
        raise


def _read_small_descriptor(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    contents = os.read(descriptor, 4097)
    os.lseek(descriptor, 0, os.SEEK_SET)
    if len(contents) > 4096:
        raise OSError("Git administration link is too large")
    return contents


def _open_git_boundary(
    lane_descriptor: int, lane_root: Path, lane_identity: tuple[int, int, int]
) -> _GitBoundary:
    dot_git_descriptor = -1
    admin_descriptor = -1
    try:
        named = os.stat(".git", dir_fd=lane_descriptor, follow_symlinks=False)
        if stat.S_ISLNK(named.st_mode):
            raise OSError("Git administration path is a symlink")
        if stat.S_ISDIR(named.st_mode):
            dot_git_type = "DIRECTORY"
            dot_git_descriptor = os.open(".git", _DIRECTORY_FLAGS, dir_fd=lane_descriptor)
            dot_git_contents = None
            admin_root = lane_root / ".git"
            admin_descriptor = os.dup(dot_git_descriptor)
        elif stat.S_ISREG(named.st_mode):
            dot_git_type = "REGULAR"
            dot_git_descriptor = os.open(".git", _READ_FLAGS, dir_fd=lane_descriptor)
            dot_git_contents = _read_small_descriptor(dot_git_descriptor)
            try:
                link = dot_git_contents.decode("utf-8", "strict")
            except UnicodeDecodeError as exc:
                raise OSError("Git administration link is not UTF-8") from exc
            if not link.endswith("\n") or link.count("\n") != 1 or not link.startswith(
                "gitdir: "
            ):
                raise OSError("Git administration link is malformed")
            admin_root = _canonical_absolute(
                Path(link.removeprefix("gitdir: ").removesuffix("\n")),
                "Git administration root",
            )
            admin_descriptor, _ = _open_absolute_directory_no_follow(admin_root)
        else:
            raise OSError("Git administration path has an unsafe type")

        opened_dot_git = os.fstat(dot_git_descriptor)
        opened_admin = os.fstat(admin_descriptor)
        if _physical_identity(named) != _physical_identity(opened_dot_git):
            raise OSError("Git administration path changed while opening")
        return _GitBoundary(
            lane_root=lane_root,
            lane_descriptor=lane_descriptor,
            lane_identity=lane_identity,
            dot_git_descriptor=dot_git_descriptor,
            dot_git_identity=_physical_identity(opened_dot_git),
            dot_git_type=dot_git_type,
            dot_git_contents=dot_git_contents,
            admin_root=admin_root,
            admin_descriptor=admin_descriptor,
            admin_identity=_physical_identity(opened_admin),
        )
    except (ControlledCoordinationError, OSError, ValueError) as exc:
        if admin_descriptor >= 0:
            os.close(admin_descriptor)
        if dot_git_descriptor >= 0:
            os.close(dot_git_descriptor)
        if isinstance(exc, ControlledCoordinationError):
            raise _error(
                "LANE_INVENTORY_UNAVAILABLE",
                "Git administration path is not physically anchored",
            ) from exc
        raise _error(
            "LANE_INVENTORY_UNAVAILABLE",
            "Git administration path is not physically anchored",
        ) from exc


def _close_git_boundary(boundary: _GitBoundary | None) -> None:
    if boundary is None:
        return
    if boundary.admin_descriptor >= 0:
        os.close(boundary.admin_descriptor)
        boundary.admin_descriptor = -1
    if boundary.dot_git_descriptor >= 0:
        os.close(boundary.dot_git_descriptor)
        boundary.dot_git_descriptor = -1


def _verify_git_boundary(boundary: _GitBoundary) -> None:
    named_lane_descriptor = -1
    named_dot_git_descriptor = -1
    named_admin_descriptor = -1
    try:
        if _physical_identity(os.fstat(boundary.lane_descriptor)) != boundary.lane_identity:
            raise OSError("held lane identity changed")
        named_lane_descriptor, named_lane = _open_absolute_directory_no_follow(
            boundary.lane_root
        )
        if _physical_identity(named_lane) != boundary.lane_identity:
            raise OSError("named lane identity changed")

        named_dot_git = os.stat(
            ".git", dir_fd=boundary.lane_descriptor, follow_symlinks=False
        )
        if stat.S_ISLNK(named_dot_git.st_mode):
            raise OSError("Git administration path became a symlink")
        dot_git_flags = (
            _DIRECTORY_FLAGS if boundary.dot_git_type == "DIRECTORY" else _READ_FLAGS
        )
        named_dot_git_descriptor = os.open(
            ".git", dot_git_flags, dir_fd=boundary.lane_descriptor
        )
        if (
            _physical_identity(os.fstat(boundary.dot_git_descriptor))
            != boundary.dot_git_identity
            or _physical_identity(named_dot_git) != boundary.dot_git_identity
            or _physical_identity(os.fstat(named_dot_git_descriptor))
            != boundary.dot_git_identity
        ):
            raise OSError("Git administration link identity changed")
        if (
            boundary.dot_git_contents is not None
            and _read_small_descriptor(boundary.dot_git_descriptor)
            != boundary.dot_git_contents
        ):
            raise OSError("Git administration link contents changed")

        named_admin_descriptor, named_admin = _open_absolute_directory_no_follow(
            boundary.admin_root
        )
        if (
            _physical_identity(os.fstat(boundary.admin_descriptor))
            != boundary.admin_identity
            or _physical_identity(named_admin) != boundary.admin_identity
        ):
            raise OSError("Git administration root identity changed")
    except OSError as exc:
        raise _error(
            "LANE_INVENTORY_UNAVAILABLE",
            "Git worktree or administration identity changed",
        ) from exc
    finally:
        for descriptor in (
            named_admin_descriptor,
            named_dot_git_descriptor,
            named_lane_descriptor,
        ):
            if descriptor >= 0:
                os.close(descriptor)


def _run_git(
    boundary: _GitBoundary, *args: str, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    try:
        _verify_git_boundary(boundary)
        completed = subprocess.run(
            [
                _GIT_PATH,
                *_GIT_DISABLED_EXECUTABLE_EXTENSIONS,
                f"--git-dir={boundary.admin_root}",
                f"--work-tree={boundary.lane_root}",
                *args,
            ],
            cwd=boundary.lane_root,
            env=_SEALED_GIT_ENVIRONMENT,
            check=False,
            capture_output=True,
        )
        _verify_git_boundary(boundary)
        if check and completed.returncode != 0:
            raise subprocess.CalledProcessError(
                completed.returncode,
                completed.args,
                output=completed.stdout,
                stderr=completed.stderr,
            )
        return completed
    except (OSError, subprocess.CalledProcessError) as exc:
        raise _error("LANE_INVENTORY_UNAVAILABLE", "Git lane inventory failed") from exc


def _validate_ephemeral_paths(boundary: _GitBoundary, ephemeral: list[str]) -> None:
    for relative in ephemeral:
        ignored = any(
            _run_git(
                boundary, "check-ignore", "-q", "--", candidate, check=False
            ).returncode
            == 0
            for candidate in (relative, f"{relative}/.guard-ignore-probe")
        )
        if not ignored:
            raise _error(
                "UNSAFE_EPHEMERAL_WRITESET",
                f"ephemeral path is not Git-ignored: {relative}",
            )
        tracked = _run_git(
            boundary,
            "ls-files",
            "--error-unmatch",
            "--",
            relative,
            check=False,
        )
        if tracked.returncode == 0:
            raise _error(
                "UNSAFE_EPHEMERAL_WRITESET",
                f"ephemeral path is already tracked: {relative}",
            )


def _parse_status(raw: bytes) -> tuple[list[str], list[str], list[str], list[str]]:
    fields = raw.split(b"\0")
    paths: list[str] = []
    tracked: list[str] = []
    untracked: list[str] = []
    ignored: list[str] = []
    index = 0
    while index < len(fields) and fields[index]:
        entry = fields[index]
        index += 1
        if len(entry) < 4 or entry[2:3] != b" ":
            raise _error("LANE_INVENTORY_UNAVAILABLE", "malformed Git status entry")
        status_code = entry[:2]
        entry_paths = [os.fsdecode(entry[3:])]
        if status_code[:1] in {b"R", b"C"} or status_code[1:2] in {b"R", b"C"}:
            if index >= len(fields) or not fields[index]:
                raise _error("LANE_INVENTORY_UNAVAILABLE", "malformed Git rename entry")
            entry_paths.append(os.fsdecode(fields[index]))
            index += 1
        normalized_paths = [
            _canonical_relative(path.rstrip("/"), "Git inventory path")
            for path in entry_paths
        ]
        paths.extend(normalized_paths)
        if status_code == b"??":
            untracked.extend(normalized_paths)
        elif status_code == b"!!":
            ignored.extend(normalized_paths)
        else:
            tracked.extend(normalized_paths)
    return (
        sorted(set(paths)),
        sorted(set(tracked)),
        sorted(set(untracked)),
        sorted(set(ignored)),
    )


def _inventory(
    lane_descriptor: int, git_boundary: _GitBoundary
) -> dict[str, object]:
    status_result = _run_git(
        git_boundary,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--ignored=matching",
        "--ignore-submodules=none",
    )
    paths, tracked, untracked, ignored = _parse_status(status_result.stdout)
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
        "ignoredPaths": ignored,
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


def _complete_persistent_breach_inventory(
    lease: dict[str, Any],
) -> tuple[dict[str, object], list[str], list[str]]:
    """Return the complete current lane inventory without trusting caller paths."""
    requested_lane = _canonical_absolute(Path(lease["laneRoot"]), "lane root")
    lane_descriptor = -1
    git_boundary: _GitBoundary | None = None
    try:
        lane_descriptor, opened = _open_absolute_directory_no_follow(requested_lane)
        expected = lease.get("lanePhysicalIdentity")
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
                "observed lane physical identity changed",
            )
        git_boundary = _open_git_boundary(
            lane_descriptor, requested_lane, _physical_identity(opened)
        )
        footprint = lease.get("fullFootprint")
        if not isinstance(footprint, dict):
            raise _error("STALE_LEASE_BINDING", "lease footprint is unavailable")
        exact = sorted(
            _canonical_relative(item, "exactWriteSet")
            for item in footprint.get("exactWriteSet", [])
        )
        ephemeral = sorted(
            _canonical_relative(item, "ephemeralWriteSet")
            for item in footprint.get("ephemeralWriteSet", [])
        )
        if len(exact) != len(set(exact)) or len(ephemeral) != len(set(ephemeral)):
            raise _error("STALE_LEASE_BINDING", "lease WriteSets are not canonical")
        inventory = _inventory(lane_descriptor, git_boundary)
        remaining_ephemeral = sorted(
            {
                *(
                    path
                    for path in inventory["paths"]
                    if any(_path_is_within(path, item) for item in ephemeral)
                ),
                *(
                    item
                    for item in ephemeral
                    if _path_exists_no_follow(lane_descriptor, item)
                ),
            }
        )
        return (
            inventory,
            _persistent_breaches(inventory["paths"], exact, ephemeral),
            remaining_ephemeral,
        )
    except OSError as exc:
        raise _error(
            "UNSAFE_WRITE_TARGET", "observed lane could not be opened no-follow"
        ) from exc
    finally:
        _close_git_boundary(git_boundary)
        if lane_descriptor >= 0:
            os.close(lane_descriptor)


def _path_exists_no_follow(lane_descriptor: int, relative: str) -> bool:
    current = os.dup(lane_descriptor)
    try:
        parts = PurePosixPath(relative).parts
        for index, part in enumerate(parts):
            final = index == len(parts) - 1
            try:
                if final:
                    os.stat(part, dir_fd=current, follow_symlinks=False)
                    return True
                following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
            except FileNotFoundError:
                return False
            except OSError:
                return True
            os.close(current)
            current = following
        return False
    finally:
        os.close(current)


def _declared_ephemeral_presence(
    lane_descriptor: int, ephemeral: list[str]
) -> tuple[list[str], list[str]]:
    existing = {
        item for item in ephemeral if _path_exists_no_follow(lane_descriptor, item)
    }
    return sorted(set(ephemeral) - existing), sorted(existing)


def _open_relative_no_follow(
    lane_descriptor: int, relative: str, *, directory: bool
) -> int:
    if not relative:
        return os.dup(lane_descriptor)
    current = os.dup(lane_descriptor)
    try:
        parts = PurePosixPath(relative).parts
        for index, part in enumerate(parts):
            final = index == len(parts) - 1
            flags = _DIRECTORY_FLAGS if not final or directory else _READ_FLAGS
            following = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = following
        result = current
        current = -1
        return result
    finally:
        if current >= 0:
            os.close(current)


def _revalidate_targets(
    lane_descriptor: int, targets: list[_AnchoredTarget]
) -> None:
    for target in targets:
        for component in target.ancestors:
            named_descriptor = -1
            try:
                named_descriptor = _open_relative_no_follow(
                    lane_descriptor, component.relative, directory=True
                )
                if (
                    _physical_identity(os.fstat(component.descriptor))
                    != component.identity
                    or _physical_identity(os.fstat(named_descriptor))
                    != component.identity
                ):
                    raise OSError("ancestor identity changed")
            except OSError as exc:
                raise _error(
                    "WRITE_TARGET_IDENTITY_CHANGED",
                    f"anchored write target ancestor changed: {target.relative}",
                ) from exc
            finally:
                if named_descriptor >= 0:
                    os.close(named_descriptor)

        named_descriptor = -1
        try:
            if target.identity is None:
                try:
                    named_descriptor = _open_relative_no_follow(
                        lane_descriptor, target.relative, directory=False
                    )
                except FileNotFoundError:
                    continue
                observed = os.fstat(named_descriptor)
                if not stat.S_ISREG(observed.st_mode) and not stat.S_ISDIR(
                    observed.st_mode
                ):
                    raise OSError("created target has an unsafe type")
                continue

            named_descriptor = _open_relative_no_follow(
                lane_descriptor,
                target.relative,
                directory=target.target_type == "DIRECTORY",
            )
            if (
                target.descriptor is None
                or _physical_identity(os.fstat(target.descriptor)) != target.identity
                or _physical_identity(os.fstat(named_descriptor)) != target.identity
            ):
                raise OSError("target identity changed")
        except OSError as exc:
            raise _error(
                "WRITE_TARGET_IDENTITY_CHANGED",
                f"anchored write target changed during execution: {target.relative}",
            ) from exc
        finally:
            if named_descriptor >= 0:
                os.close(named_descriptor)


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
            "(allow process-exec*)",
            "(deny process-fork)",
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


def _run_sandboxed(
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    profile: str,
) -> subprocess.CompletedProcess[bytes]:
    command = [_SANDBOX_EXEC_PATH, "-p", profile, *argv]
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise _error(
            "PROCESS_SANDBOX_UNAVAILABLE", "sandboxed command could not start"
        ) from exc
    return subprocess.CompletedProcess(
        argv, completed.returncode, completed.stdout, completed.stderr
    )


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


def _quarantine_guard_breach(
    store: CoordinatorStateStore,
    journal: dict[str, Any],
    lease: dict[str, Any],
    inventory: dict[str, object],
    observed_paths: list[str],
    ephemeral_paths_removed: list[str],
) -> None:
    from .controlled_coordinator_inputs import normalize_write_observation_command
    from .controlled_recovery import quarantine_observed_writes_locked

    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    command: dict[str, Any] = {
        "schemaVersion": "controlled-write-observation-command/v1",
        "projectExecutionKey": lease["projectExecutionKey"],
        "leaseId": lease["leaseId"],
        "fencingToken": lease["fencingToken"],
        "beforeInventoryDigest": "sha256:"
        + hashlib.sha256(canonical_json_bytes(inventory)).hexdigest(),
        "observedPaths": sorted(observed_paths),
        "ephemeralPathsRemoved": sorted(ephemeral_paths_removed),
        "processQuiescence": {
            "status": "QUIESCENT",
            "observedAt": observed_at,
            "processIds": [],
        },
    }
    command["commandDigest"] = "sha256:" + hashlib.sha256(
        canonical_json_bytes(command)
    ).hexdigest()
    normalized = normalize_write_observation_command(Path(__file__).parents[2], command)
    quarantine_observed_writes_locked(store, journal, normalized, observed_paths)


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
            journal = store.read_journal()
            durable = _current_durable_lease(journal, lease)
            assert journal is not None
            if durable["laneRoot"] != str(requested_lane):
                raise _error("STALE_LEASE_BINDING", "lane root is not lease-owned")
            lane_descriptor = -1
            targets: list[_AnchoredTarget] = []
            git_boundary: _GitBoundary | None = None
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
                git_boundary = _open_git_boundary(
                    lane_descriptor, requested_lane, _physical_identity(opened)
                )
                targets, exact, ephemeral = _validate_declared_sets(
                    lane_descriptor, requested_lane, git_boundary, durable
                )
                before = _inventory(lane_descriptor, git_boundary)
                before_breaches = _persistent_breaches(
                    before["paths"], exact, ephemeral
                )
                if before_breaches:
                    removed_ephemeral, _remaining_ephemeral = (
                        _declared_ephemeral_presence(lane_descriptor, ephemeral)
                    )
                    _quarantine_guard_breach(
                        store,
                        journal,
                        durable,
                        before,
                        before_breaches,
                        removed_ephemeral,
                    )
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
                after = _inventory(lane_descriptor, git_boundary)
                _revalidate_targets(lane_descriptor, targets)
                after_breaches = _persistent_breaches(after["paths"], exact, ephemeral)
                if after_breaches:
                    removed_ephemeral, _remaining_ephemeral = (
                        _declared_ephemeral_presence(lane_descriptor, ephemeral)
                    )
                    _quarantine_guard_breach(
                        store,
                        journal,
                        durable,
                        before,
                        after_breaches,
                        removed_ephemeral,
                    )
                    raise _error(
                        "WRITESET_BREACH",
                        "guarded command produced persistent paths outside exactWriteSet",
                        observed_paths=after_breaches,
                    )
                remaining_ephemeral = sorted(
                    {
                        *(
                            path
                            for path in after["paths"]
                            if any(
                                _path_is_within(path, item) for item in ephemeral
                            )
                        ),
                        *(
                            item
                            for item in ephemeral
                            if _path_exists_no_follow(lane_descriptor, item)
                        ),
                    }
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
                _close_git_boundary(git_boundary)
                if lane_descriptor >= 0:
                    os.close(lane_descriptor)
