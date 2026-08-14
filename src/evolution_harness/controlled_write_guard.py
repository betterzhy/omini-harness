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
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
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
    commondir_descriptor: int
    commondir_identity: tuple[int, int, int] | None
    commondir_contents: bytes | None
    common_admin_root: Path
    common_admin_descriptor: int
    common_admin_identity: tuple[int, int, int]
    objects_descriptor: int
    objects_identity: tuple[int, int, int]
    git_descriptor: int
    git_identity: tuple[int, int, int]
    error_code: str
    error_message: str


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


def _read_bounded_regular_file(
    root_descriptor: int, relative: str, *, maximum: int
) -> bytes:
    descriptor = -1
    try:
        descriptor = _open_relative_no_follow(
            root_descriptor, relative, directory=False
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise OSError("Git control file is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        contents = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            _physical_identity(before) != _physical_identity(after)
            or len(contents) > maximum
        ):
            raise OSError("Git control file changed during descriptor read")
        return contents
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _canonical_git_oid(raw: bytes) -> str | None:
    try:
        value = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    if len(value) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in value
    ):
        return None
    return value


def _canonical_git_ref(raw: bytes) -> str:
    try:
        value = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise OSError("Git symbolic ref is not UTF-8") from exc
    path = PurePosixPath(value)
    if (
        not value.startswith("refs/")
        or len(value) > 1024
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(character in value for character in ("\\", "\x00", "\r", "\n"))
    ):
        raise OSError("Git symbolic ref is not canonical")
    return value


def _packed_ref_oid(boundary: _GitBoundary, reference: str) -> str:
    packed = _read_bounded_regular_file(
        boundary.common_admin_descriptor,
        "packed-refs",
        maximum=16 * 1024 * 1024,
    )
    matches: list[str] = []
    for line in packed.splitlines():
        if not line or line.startswith((b"#", b"^")):
            continue
        fields = line.split(b" ")
        if len(fields) != 2:
            raise OSError("Git packed-refs contains a malformed entry")
        try:
            packed_reference = fields[1].decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise OSError("Git packed ref is not UTF-8") from exc
        if packed_reference == reference:
            oid = _canonical_git_oid(fields[0])
            if oid is None:
                raise OSError("Git packed ref object identity is malformed")
            matches.append(oid)
    if len(matches) != 1:
        raise OSError("Git packed ref is absent or ambiguous")
    return matches[0]


def _read_git_head(boundary: _GitBoundary) -> str:
    try:
        _verify_git_boundary(boundary)
        contents = _read_bounded_regular_file(
            boundary.admin_descriptor, "HEAD", maximum=4096
        )
        seen: set[str] = set()
        for _ in range(8):
            if not contents.endswith(b"\n") or contents.count(b"\n") != 1:
                raise OSError("Git HEAD/ref is not one canonical line")
            value = contents[:-1]
            oid = _canonical_git_oid(value)
            if oid is not None:
                _verify_git_boundary(boundary)
                return oid
            if not value.startswith(b"ref: "):
                raise OSError("Git HEAD/ref has no canonical object identity")
            reference = _canonical_git_ref(value.removeprefix(b"ref: "))
            if reference in seen:
                raise OSError("Git symbolic refs contain a cycle")
            seen.add(reference)
            contents = b""
            found_loose_ref = False
            for root_descriptor in (
                boundary.admin_descriptor,
                boundary.common_admin_descriptor,
            ):
                try:
                    contents = _read_bounded_regular_file(
                        root_descriptor, reference, maximum=4096
                    )
                except FileNotFoundError:
                    continue
                found_loose_ref = True
                break
            if not found_loose_ref:
                oid = _packed_ref_oid(boundary, reference)
                _verify_git_boundary(boundary)
                return oid
        raise OSError("Git symbolic ref depth exceeds the sealed limit")
    except (ControlledCoordinationError, OSError, ValueError) as exc:
        if isinstance(exc, ControlledCoordinationError):
            raise
        raise _error(boundary.error_code, boundary.error_message) from exc


def _run_git_object_batch(
    boundary: _GitBoundary, object_id: str, *, check_only: bool
) -> bytes:
    environment = dict(_SEALED_GIT_ENVIRONMENT)
    environment["GIT_OBJECT_DIRECTORY"] = "."

    def enter_held_object_root() -> None:
        os.fchdir(boundary.objects_descriptor)

    arguments = [
        _GIT_PATH,
        *_GIT_DISABLED_EXECUTABLE_EXTENSIONS,
        f"--git-dir={boundary.admin_root}",
        "cat-file",
        "--batch-check" if check_only else "--batch",
    ]
    return subprocess.run(
        arguments,
        cwd="/",
        env=environment,
        input=f"{object_id}\n".encode("ascii"),
        check=False,
        capture_output=True,
        timeout=10,
        pass_fds=(boundary.objects_descriptor,),
        preexec_fn=enter_held_object_root,
    ).stdout


def _read_git_object(
    boundary: _GitBoundary,
    object_id: str,
    *,
    expected_type: str,
    maximum: int = 64 * 1024 * 1024,
) -> bytes:
    try:
        canonical = _canonical_git_oid(object_id.encode("ascii", "strict"))
        if canonical != object_id or expected_type not in {"commit", "tree"}:
            raise OSError("Git object request is not canonical")
        _verify_git_boundary(boundary)
        checked = _run_git_object_batch(boundary, object_id, check_only=True)
        checked_fields = checked.removesuffix(b"\n").split(b" ")
        if len(checked_fields) != 3:
            raise OSError("Git object metadata is unavailable")
        returned_oid = _canonical_git_oid(checked_fields[0])
        try:
            returned_type = checked_fields[1].decode("ascii", "strict")
            size = int(checked_fields[2].decode("ascii", "strict"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise OSError("Git object metadata is malformed") from exc
        if (
            returned_oid != object_id
            or returned_type != expected_type
            or size < 0
            or size > maximum
            or checked_fields[2] != str(size).encode("ascii")
        ):
            raise OSError("Git object metadata does not match the sealed request")

        output = _run_git_object_batch(boundary, object_id, check_only=False)
        header, separator, remainder = output.partition(b"\n")
        fields = header.split(b" ")
        if not separator or len(fields) != 3:
            raise OSError("Git object output has no canonical batch header")
        output_oid = _canonical_git_oid(fields[0])
        try:
            output_type = fields[1].decode("ascii", "strict")
            output_size = int(fields[2].decode("ascii", "strict"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise OSError("Git object output header is malformed") from exc
        if (
            output_oid != object_id
            or output_type != expected_type
            or output_size != size
            or fields[2] != str(output_size).encode("ascii")
            or len(remainder) != output_size + 1
            or not remainder.endswith(b"\n")
        ):
            raise OSError("Git object output does not match its metadata")
        body = remainder[:-1]
        object_bytes = f"{output_type} {output_size}\0".encode("ascii") + body
        hasher = hashlib.sha1 if len(object_id) == 40 else hashlib.sha256
        if hasher(object_bytes).hexdigest() != object_id:
            raise OSError("Git object output does not reproduce its requested hash")
        _verify_git_boundary(boundary)
        return body
    except (
        ControlledCoordinationError,
        OSError,
        subprocess.SubprocessError,
        UnicodeEncodeError,
    ) as exc:
        if isinstance(exc, ControlledCoordinationError):
            raise
        raise _error(boundary.error_code, boundary.error_message) from exc


def _verify_no_git_object_alternates(objects_descriptor: int) -> None:
    info_descriptor = -1
    try:
        try:
            info_descriptor = os.open(
                "info", _DIRECTORY_FLAGS, dir_fd=objects_descriptor
            )
        except FileNotFoundError:
            return
        try:
            os.stat(
                "alternates", dir_fd=info_descriptor, follow_symlinks=False
            )
        except FileNotFoundError:
            return
        raise OSError("Git object alternates are not a sealed object view")
    finally:
        if info_descriptor >= 0:
            os.close(info_descriptor)


def _open_git_boundary(
    lane_descriptor: int,
    lane_root: Path,
    lane_identity: tuple[int, int, int],
    *,
    error_code: str = "LANE_INVENTORY_UNAVAILABLE",
    error_message: str = "Git administration path is not physically anchored",
) -> _GitBoundary:
    dot_git_descriptor = -1
    admin_descriptor = -1
    commondir_descriptor = -1
    common_admin_descriptor = -1
    objects_descriptor = -1
    git_descriptor = -1
    try:
        if _GIT_PATH != "/usr/bin/git":
            raise OSError("Git executable path is not the fixed system path")
        named_git = os.stat(_GIT_PATH, follow_symlinks=False)
        git_descriptor = os.open(_GIT_PATH, _READ_FLAGS)
        opened_git = os.fstat(git_descriptor)
        if (
            not stat.S_ISREG(opened_git.st_mode)
            or opened_git.st_uid != 0
            or opened_git.st_gid != 0
            or not stat.S_IMODE(opened_git.st_mode) & 0o111
            or stat.S_IMODE(opened_git.st_mode) & (stat.S_IWGRP | stat.S_IWOTH)
            or _physical_identity(named_git) != _physical_identity(opened_git)
        ):
            raise OSError("Git executable identity or ownership is unsafe")
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

        try:
            commondir_named = os.stat(
                "commondir", dir_fd=admin_descriptor, follow_symlinks=False
            )
        except FileNotFoundError:
            commondir_named = None
        if commondir_named is None:
            commondir_identity = None
            commondir_contents = None
            common_admin_root = admin_root
            common_admin_descriptor = os.dup(admin_descriptor)
        else:
            if not stat.S_ISREG(commondir_named.st_mode):
                raise OSError("Git commondir control path is not a regular file")
            commondir_descriptor = os.open(
                "commondir", _READ_FLAGS, dir_fd=admin_descriptor
            )
            opened_commondir = os.fstat(commondir_descriptor)
            if _physical_identity(commondir_named) != _physical_identity(
                opened_commondir
            ):
                raise OSError("Git commondir identity changed while opening")
            commondir_identity = _physical_identity(opened_commondir)
            commondir_contents = _read_small_descriptor(commondir_descriptor)
            try:
                commondir_link = commondir_contents.decode("utf-8", "strict")
            except UnicodeDecodeError as exc:
                raise OSError("Git commondir is not UTF-8") from exc
            if (
                not commondir_link.endswith("\n")
                or commondir_link.count("\n") != 1
                or "\x00" in commondir_link
            ):
                raise OSError("Git commondir is malformed")
            raw_common = commondir_link.removesuffix("\n")
            if not raw_common:
                raise OSError("Git commondir is empty")
            common_admin_root = _canonical_absolute(
                Path(os.path.normpath(os.path.join(admin_root, raw_common))),
                "Git common administration root",
            )
            common_admin_descriptor, _ = _open_absolute_directory_no_follow(
                common_admin_root
            )

        opened_common_admin = os.fstat(common_admin_descriptor)
        objects_descriptor = os.open(
            "objects", _DIRECTORY_FLAGS, dir_fd=common_admin_descriptor
        )
        opened_objects = os.fstat(objects_descriptor)
        _verify_no_git_object_alternates(objects_descriptor)

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
            commondir_descriptor=commondir_descriptor,
            commondir_identity=commondir_identity,
            commondir_contents=commondir_contents,
            common_admin_root=common_admin_root,
            common_admin_descriptor=common_admin_descriptor,
            common_admin_identity=_physical_identity(opened_common_admin),
            objects_descriptor=objects_descriptor,
            objects_identity=_physical_identity(opened_objects),
            git_descriptor=git_descriptor,
            git_identity=_physical_identity(opened_git),
            error_code=error_code,
            error_message=error_message,
        )
    except (ControlledCoordinationError, OSError, ValueError) as exc:
        if objects_descriptor >= 0:
            os.close(objects_descriptor)
        if common_admin_descriptor >= 0:
            os.close(common_admin_descriptor)
        if commondir_descriptor >= 0:
            os.close(commondir_descriptor)
        if git_descriptor >= 0:
            os.close(git_descriptor)
        if admin_descriptor >= 0:
            os.close(admin_descriptor)
        if dot_git_descriptor >= 0:
            os.close(dot_git_descriptor)
        if isinstance(exc, ControlledCoordinationError):
            raise _error(error_code, error_message) from exc
        raise _error(error_code, error_message) from exc


def _close_git_boundary(boundary: _GitBoundary | None) -> None:
    if boundary is None:
        return
    if boundary.admin_descriptor >= 0:
        os.close(boundary.admin_descriptor)
        boundary.admin_descriptor = -1
    if boundary.objects_descriptor >= 0:
        os.close(boundary.objects_descriptor)
        boundary.objects_descriptor = -1
    if boundary.common_admin_descriptor >= 0:
        os.close(boundary.common_admin_descriptor)
        boundary.common_admin_descriptor = -1
    if boundary.commondir_descriptor >= 0:
        os.close(boundary.commondir_descriptor)
        boundary.commondir_descriptor = -1
    if boundary.dot_git_descriptor >= 0:
        os.close(boundary.dot_git_descriptor)
        boundary.dot_git_descriptor = -1
    if boundary.git_descriptor >= 0:
        os.close(boundary.git_descriptor)
        boundary.git_descriptor = -1


def _verify_git_boundary(boundary: _GitBoundary) -> None:
    named_lane_descriptor = -1
    named_dot_git_descriptor = -1
    named_admin_descriptor = -1
    named_commondir_descriptor = -1
    named_common_admin_descriptor = -1
    named_objects_descriptor = -1
    try:
        named_git = os.stat(_GIT_PATH, follow_symlinks=False)
        if (
            _physical_identity(os.fstat(boundary.git_descriptor))
            != boundary.git_identity
            or _physical_identity(named_git) != boundary.git_identity
        ):
            raise OSError("fixed Git executable identity changed")
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
        if boundary.commondir_descriptor >= 0:
            named_commondir = os.stat(
                "commondir",
                dir_fd=boundary.admin_descriptor,
                follow_symlinks=False,
            )
            named_commondir_descriptor = os.open(
                "commondir", _READ_FLAGS, dir_fd=boundary.admin_descriptor
            )
            if (
                boundary.commondir_identity is None
                or _physical_identity(os.fstat(boundary.commondir_descriptor))
                != boundary.commondir_identity
                or _physical_identity(named_commondir)
                != boundary.commondir_identity
                or _physical_identity(os.fstat(named_commondir_descriptor))
                != boundary.commondir_identity
                or _read_small_descriptor(boundary.commondir_descriptor)
                != boundary.commondir_contents
            ):
                raise OSError("Git commondir identity or contents changed")
        else:
            try:
                os.stat(
                    "commondir",
                    dir_fd=boundary.admin_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                raise OSError("Git commondir appeared during the sealed read")

        named_common_admin_descriptor, named_common_admin = (
            _open_absolute_directory_no_follow(boundary.common_admin_root)
        )
        if (
            _physical_identity(os.fstat(boundary.common_admin_descriptor))
            != boundary.common_admin_identity
            or _physical_identity(named_common_admin)
            != boundary.common_admin_identity
        ):
            raise OSError("Git common administration root identity changed")
        named_objects = os.stat(
            "objects",
            dir_fd=boundary.common_admin_descriptor,
            follow_symlinks=False,
        )
        named_objects_descriptor = os.open(
            "objects", _DIRECTORY_FLAGS, dir_fd=boundary.common_admin_descriptor
        )
        if (
            _physical_identity(os.fstat(boundary.objects_descriptor))
            != boundary.objects_identity
            or _physical_identity(named_objects) != boundary.objects_identity
            or _physical_identity(os.fstat(named_objects_descriptor))
            != boundary.objects_identity
        ):
            raise OSError("Git common object root identity changed")
        _verify_no_git_object_alternates(boundary.objects_descriptor)
    except OSError as exc:
        raise _error(boundary.error_code, boundary.error_message) from exc
    finally:
        for descriptor in (
            named_admin_descriptor,
            named_objects_descriptor,
            named_common_admin_descriptor,
            named_commondir_descriptor,
            named_dot_git_descriptor,
            named_lane_descriptor,
        ):
            if descriptor >= 0:
                os.close(descriptor)


def _run_git(
    boundary: _GitBoundary, *args: str
) -> subprocess.CompletedProcess[bytes]:
    if args != ("ls-files", "-z", "--stage"):
        raise _error(
            "LANE_INVENTORY_UNAVAILABLE",
            "only descriptor-bound index inventory is available",
        )
    if (
        boundary.dot_git_type != "DIRECTORY"
        or boundary.commondir_descriptor >= 0
        or boundary.admin_identity != boundary.common_admin_identity
    ):
        raise _error(
            "LANE_INVENTORY_UNAVAILABLE",
            "linked-worktree inventory is not descriptor-bound",
        )
    index_descriptor = -1
    try:
        _verify_git_boundary(boundary)
        index_descriptor = os.open(
            "index", _READ_FLAGS, dir_fd=boundary.admin_descriptor
        )
        before = os.fstat(index_descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 64 * 1024 * 1024:
            raise OSError("Git index is not a bounded regular file")
        environment = dict(_SEALED_GIT_ENVIRONMENT)
        environment["GIT_INDEX_FILE"] = f"/dev/fd/{index_descriptor}"

        def enter_held_admin_root() -> None:
            os.fchdir(boundary.admin_descriptor)

        completed = subprocess.run(
            [
                _GIT_PATH,
                *_GIT_DISABLED_EXECUTABLE_EXTENSIONS,
                "--git-dir=.",
                f"--work-tree=/dev/fd/{boundary.lane_descriptor}",
                *args,
            ],
            cwd="/",
            env=environment,
            check=False,
            capture_output=True,
            timeout=10,
            pass_fds=(
                boundary.admin_descriptor,
                boundary.lane_descriptor,
                index_descriptor,
            ),
            preexec_fn=enter_held_admin_root,
        )
        after = os.fstat(index_descriptor)
        _verify_git_boundary(boundary)
        if (
            _physical_identity(before) != _physical_identity(after)
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or len(completed.stdout) > 64 * 1024 * 1024
        ):
            raise OSError("Git index changed during descriptor-bound inventory")
        if completed.returncode != 0:
            raise subprocess.CalledProcessError(
                completed.returncode,
                completed.args,
                output=completed.stdout,
                stderr=completed.stderr,
            )
        return completed
    except (OSError, subprocess.SubprocessError) as exc:
        raise _error("LANE_INVENTORY_UNAVAILABLE", "Git lane inventory failed") from exc
    finally:
        if index_descriptor >= 0:
            os.close(index_descriptor)


def _read_git_index(boundary: _GitBoundary) -> dict[str, tuple[str, str]]:
    raw = _run_git(boundary, "ls-files", "-z", "--stage").stdout
    entries: dict[str, tuple[str, str]] = {}
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    for field in fields:
        metadata, separator, raw_path = field.partition(b"\t")
        parts = metadata.split(b" ")
        if not separator or len(parts) != 3 or parts[2] != b"0":
            raise _error(
                "LANE_INVENTORY_UNAVAILABLE",
                "Git index contains an unsupported or unmerged entry",
            )
        try:
            mode = parts[0].decode("ascii", "strict")
            path = raw_path.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise _error(
                "LANE_INVENTORY_UNAVAILABLE", "Git index path is not canonical UTF-8"
            ) from exc
        object_id = _canonical_git_oid(parts[1])
        if mode not in {"100644", "100755", "120000"} or object_id is None:
            raise _error(
                "LANE_INVENTORY_UNAVAILABLE",
                "Git index contains an unsupported entry type",
            )
        try:
            canonical = _canonical_relative(path, "Git index path")
        except ControlledCoordinationError as exc:
            raise _error(
                "LANE_INVENTORY_UNAVAILABLE", "Git index path is not canonical"
            ) from exc
        if canonical in entries:
            raise _error(
                "LANE_INVENTORY_UNAVAILABLE", "Git index path is ambiguous"
            )
        entries[canonical] = (mode, object_id)
    return entries


def _commit_tree_identity(commit_body: bytes) -> str:
    header, separator, _message = commit_body.partition(b"\n\n")
    if not separator:
        raise OSError("Git commit has no canonical header terminator")
    trees = [
        line.removeprefix(b"tree ")
        for line in header.splitlines()
        if line.startswith(b"tree ")
    ]
    if len(trees) != 1:
        raise OSError("Git commit does not contain exactly one tree")
    tree = _canonical_git_oid(trees[0])
    if tree is None:
        raise OSError("Git commit tree identity is malformed")
    return tree


def _read_committed_entries(
    boundary: _GitBoundary,
) -> dict[str, tuple[str, str]]:
    try:
        head = _read_git_head(boundary)
        tree = _commit_tree_identity(
            _read_git_object(boundary, head, expected_type="commit")
        )
        entries: dict[str, tuple[str, str]] = {}
        object_bytes = len(tree) // 2
        expanded_entries = 0

        def walk_tree(
            tree_id: str,
            prefix: PurePosixPath | None,
            ancestors: frozenset[str],
            depth: int,
        ) -> None:
            nonlocal expanded_entries
            if depth > 64 or tree_id in ancestors:
                raise OSError("Git tree nesting is cyclic or too deep")
            body = _read_git_object(boundary, tree_id, expected_type="tree")
            offset = 0
            local_names: set[str] = set()
            while offset < len(body):
                space = body.find(b" ", offset)
                nul = body.find(b"\0", space + 1) if space >= 0 else -1
                end = nul + 1 + object_bytes
                if space <= offset or nul <= space + 1 or end > len(body):
                    raise OSError("Git tree entry is truncated or malformed")
                try:
                    mode = body[offset:space].decode("ascii", "strict")
                    name = body[space + 1 : nul].decode("utf-8", "strict")
                except UnicodeDecodeError as exc:
                    raise OSError("Git tree entry is not canonical UTF-8") from exc
                if (
                    not name
                    or name in {".", ".."}
                    or "/" in name
                    or name in local_names
                ):
                    raise OSError("Git tree entry name is unsafe or ambiguous")
                local_names.add(name)
                object_id = body[nul + 1 : end].hex()
                if _canonical_git_oid(object_id.encode("ascii")) != object_id:
                    raise OSError("Git tree object identity is malformed")
                relative_path = (
                    PurePosixPath(name)
                    if prefix is None
                    else prefix / name
                )
                relative = relative_path.as_posix()
                if relative == ".git" or relative.startswith(".git/"):
                    raise OSError("Git tree contains an administration path")
                expanded_entries += 1
                if expanded_entries > 100_000:
                    raise OSError("Git tree inventory exceeds the sealed limit")
                if mode == "40000":
                    walk_tree(
                        object_id,
                        relative_path,
                        ancestors | {tree_id},
                        depth + 1,
                    )
                elif mode in {"100644", "100755", "120000"}:
                    if relative in entries:
                        raise OSError("Git committed path is ambiguous")
                    entries[relative] = (mode, object_id)
                else:
                    raise OSError("Git tree contains an unsupported entry type")
                offset = end

        walk_tree(tree, None, frozenset(), 0)
        return entries
    except (ControlledCoordinationError, OSError, ValueError) as exc:
        if isinstance(exc, ControlledCoordinationError):
            raise
        raise _error(boundary.error_code, boundary.error_message) from exc


def _literal_ignored_roots(lane_descriptor: int) -> set[str]:
    try:
        raw = _read_bounded_regular_file(
            lane_descriptor, ".gitignore", maximum=1024 * 1024
        )
    except FileNotFoundError:
        return set()
    try:
        lines = raw.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError:
        return set()
    if any(line.startswith("!") for line in lines):
        return set()
    roots: set[str] = set()
    for line in lines:
        if not line or line.startswith("#") or not line.endswith("/"):
            continue
        candidate = line.removeprefix("/").removesuffix("/")
        if (
            not candidate
            or any(character in candidate for character in "*?[\\")
            or candidate != candidate.strip()
        ):
            continue
        try:
            roots.add(_canonical_relative(candidate, "literal Git ignore root"))
        except ControlledCoordinationError:
            continue
    return roots


def _validate_ephemeral_paths(boundary: _GitBoundary, ephemeral: list[str]) -> None:
    ignored_roots = _literal_ignored_roots(boundary.lane_descriptor)
    tracked_paths = set(_read_git_index(boundary)) | set(
        _read_committed_entries(boundary)
    )
    for relative in ephemeral:
        if not any(_path_is_within(relative, root) for root in ignored_roots):
            raise _error(
                "UNSAFE_EPHEMERAL_WRITESET",
                f"ephemeral path lacks a sealed literal ignore rule: {relative}",
            )
        if any(_path_is_within(path, relative) for path in tracked_paths):
            raise _error(
                "UNSAFE_EPHEMERAL_WRITESET",
                f"ephemeral path is already tracked: {relative}",
            )


def _stable_physical_stat(current: os.stat_result) -> tuple[object, ...]:
    return (
        *_physical_identity(current),
        stat.S_IMODE(current.st_mode),
        current.st_size,
        current.st_mtime_ns,
        current.st_ctime_ns,
    )


def _scan_lane_tree(
    lane_descriptor: int,
) -> tuple[dict[str, dict[str, object]], set[str]]:
    nodes: dict[str, dict[str, object]] = {}
    leaf_paths: set[str] = set()
    observed_count = 0
    observed_bytes = 0

    def visit(
        directory_descriptor: int,
        prefix: PurePosixPath | None,
        *,
        root: bool,
        depth: int,
    ) -> int:
        nonlocal observed_count, observed_bytes
        if depth > 64:
            raise OSError("lane inventory nesting exceeds the sealed limit")
        names = os.listdir(directory_descriptor)
        visible = 0
        for name in sorted(names):
            if root and name == ".git":
                continue
            try:
                canonical_name = os.fsencode(name).decode("utf-8", "strict")
            except UnicodeDecodeError as exc:
                raise OSError("lane inventory path is not canonical UTF-8") from exc
            if canonical_name in {"", ".", ".."} or "/" in canonical_name:
                raise OSError("lane inventory path component is unsafe")
            relative_path = (
                PurePosixPath(canonical_name)
                if prefix is None
                else prefix / canonical_name
            )
            relative = relative_path.as_posix()
            _canonical_relative(relative, "lane inventory path")
            before = os.stat(
                name, dir_fd=directory_descriptor, follow_symlinks=False
            )
            observed_count += 1
            visible += 1
            if observed_count > 100_000:
                raise OSError("lane inventory entry count exceeds the sealed limit")

            if stat.S_ISDIR(before.st_mode):
                child = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory_descriptor)
                try:
                    opened = os.fstat(child)
                    if _physical_identity(before) != _physical_identity(opened):
                        raise OSError("lane directory changed while opening")
                    nodes[relative] = {
                        "type": "DIRECTORY",
                        "device": opened.st_dev,
                        "inode": opened.st_ino,
                        "sha256": None,
                        "_mode": None,
                        "_gitSha1": None,
                        "_gitSha256": None,
                        "_physicalMode": stat.S_IMODE(opened.st_mode),
                    }
                    child_count = visit(
                        child, relative_path, root=False, depth=depth + 1
                    )
                    after = os.fstat(child)
                    after_named = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        _stable_physical_stat(opened)
                        != _stable_physical_stat(after)
                        or _stable_physical_stat(before)
                        != _stable_physical_stat(after_named)
                    ):
                        raise OSError("lane directory changed during inventory")
                    if child_count == 0:
                        leaf_paths.add(relative)
                finally:
                    os.close(child)
                continue

            if stat.S_ISREG(before.st_mode):
                descriptor = os.open(name, _READ_FLAGS, dir_fd=directory_descriptor)
                try:
                    opened = os.fstat(descriptor)
                    if (
                        _physical_identity(before) != _physical_identity(opened)
                        or opened.st_size > 256 * 1024 * 1024
                    ):
                        raise OSError("lane file is not a bounded stable regular file")
                    observed_bytes += opened.st_size
                    if observed_bytes > 1024 * 1024 * 1024:
                        raise OSError("lane inventory bytes exceed the sealed limit")
                    plain = hashlib.sha256()
                    git_sha1 = hashlib.sha1()
                    git_sha256 = hashlib.sha256()
                    header = f"blob {opened.st_size}\0".encode("ascii")
                    git_sha1.update(header)
                    git_sha256.update(header)
                    while True:
                        chunk = os.read(descriptor, 1024 * 1024)
                        if not chunk:
                            break
                        plain.update(chunk)
                        git_sha1.update(chunk)
                        git_sha256.update(chunk)
                    after = os.fstat(descriptor)
                    after_named = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        _stable_physical_stat(opened)
                        != _stable_physical_stat(after)
                        or _stable_physical_stat(before)
                        != _stable_physical_stat(after_named)
                    ):
                        raise OSError("lane file changed during inventory")
                    nodes[relative] = {
                        "type": "REGULAR",
                        "device": opened.st_dev,
                        "inode": opened.st_ino,
                        "sha256": plain.hexdigest(),
                        "_mode": (
                            "100755" if stat.S_IMODE(opened.st_mode) & 0o111 else "100644"
                        ),
                        "_gitSha1": git_sha1.hexdigest(),
                        "_gitSha256": git_sha256.hexdigest(),
                        "_physicalMode": stat.S_IMODE(opened.st_mode),
                    }
                finally:
                    os.close(descriptor)
                leaf_paths.add(relative)
                continue

            if stat.S_ISLNK(before.st_mode):
                target = os.readlink(
                    os.fsencode(name), dir_fd=directory_descriptor
                )
                if isinstance(target, str):
                    target = os.fsencode(target)
                after_named = os.stat(
                    name, dir_fd=directory_descriptor, follow_symlinks=False
                )
                if _stable_physical_stat(before) != _stable_physical_stat(after_named):
                    raise OSError("lane symlink changed during inventory")
                header = f"blob {len(target)}\0".encode("ascii")
                nodes[relative] = {
                    "type": "SYMLINK",
                    "device": before.st_dev,
                    "inode": before.st_ino,
                    "sha256": None,
                    "_mode": "120000",
                    "_gitSha1": hashlib.sha1(header + target).hexdigest(),
                    "_gitSha256": hashlib.sha256(header + target).hexdigest(),
                    "_physicalMode": stat.S_IMODE(before.st_mode),
                }
                leaf_paths.add(relative)
                continue

            after_named = os.stat(
                name, dir_fd=directory_descriptor, follow_symlinks=False
            )
            if _stable_physical_stat(before) != _stable_physical_stat(after_named):
                raise OSError("lane special path changed during inventory")
            nodes[relative] = {
                "type": "OTHER",
                "device": before.st_dev,
                "inode": before.st_ino,
                "sha256": None,
                "_mode": None,
                "_gitSha1": None,
                "_gitSha256": None,
                "_physicalMode": stat.S_IMODE(before.st_mode),
            }
            leaf_paths.add(relative)
        return visible

    root_descriptor = os.dup(lane_descriptor)
    try:
        visit(root_descriptor, None, root=True, depth=0)
    finally:
        os.close(root_descriptor)
    return nodes, leaf_paths


def _node_matches_git_entry(
    node: dict[str, object] | None, expected: tuple[str, str]
) -> bool:
    if node is None:
        return False
    mode, object_id = expected
    digest_key = "_gitSha1" if len(object_id) == 40 else "_gitSha256"
    return node.get("_mode") == mode and node.get(digest_key) == object_id


def _inventory(
    lane_descriptor: int,
    git_boundary: _GitBoundary,
    physical_snapshot: tuple[dict[str, dict[str, object]], set[str]] | None = None,
) -> dict[str, object]:
    _verify_git_boundary(git_boundary)
    committed = _read_committed_entries(git_boundary)
    indexed = _read_git_index(git_boundary)
    nodes, physical_leaves = (
        _scan_lane_tree(lane_descriptor)
        if physical_snapshot is None
        else physical_snapshot
    )
    _verify_git_boundary(git_boundary)

    tracked = {
        path
        for path, expected in committed.items()
        if not _node_matches_git_entry(nodes.get(path), expected)
    }
    tracked.update(
        path
        for path in set(committed) | set(indexed)
        if committed.get(path) != indexed.get(path)
    )
    untracked = {
        path
        for path in physical_leaves
        if path not in committed and path not in tracked
        and nodes[path]["type"] != "DIRECTORY"
    }
    ignored_roots = _literal_ignored_roots(lane_descriptor)
    ignored: set[str] = set()
    for path in list(untracked):
        matches = [
            root for root in ignored_roots if _path_is_within(path, root)
        ]
        if not matches:
            continue
        ignored.add(min(matches, key=lambda item: len(PurePosixPath(item).parts)))
        untracked.remove(path)
    ignored.update(
        root
        for root in ignored_roots
        if root in nodes
        and nodes[root]["type"] == "DIRECTORY"
        and not any(_path_is_within(path, root) for path in committed)
    )

    paths = sorted(tracked | untracked | ignored)
    entries: list[dict[str, object]] = []
    symlinks: list[str] = []
    for relative in paths:
        node = nodes.get(relative)
        if node is None:
            identity = {
                "type": "ABSENT",
                "device": None,
                "inode": None,
                "sha256": None,
            }
        else:
            identity = {
                key: node[key]
                for key in ("type", "device", "inode", "sha256")
            }
            if identity["type"] == "SYMLINK":
                symlinks.append(relative)
        entries.append({"path": relative, **identity})
    return {
        "paths": paths,
        "trackedPaths": sorted(tracked),
        "untrackedPaths": sorted(untracked),
        "ignoredPaths": sorted(ignored),
        "symlinkPaths": sorted(set(symlinks)),
        "entries": entries,
    }


def _physical_snapshot_changes(
    before: tuple[dict[str, dict[str, object]], set[str]],
    after: tuple[dict[str, dict[str, object]], set[str]],
) -> list[str]:
    before_nodes, before_leaves = before
    after_nodes, after_leaves = after
    stable_directories = {
        path
        for path in set(before_nodes) & set(after_nodes)
        if before_nodes[path]["type"] == "DIRECTORY"
        and after_nodes[path]["type"] == "DIRECTORY"
    }
    return sorted(
        path
        for path in before_leaves | after_leaves | stable_directories
        if before_nodes.get(path) != after_nodes.get(path)
    )


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
                before_snapshot = _scan_lane_tree(lane_descriptor)
                before = _inventory(
                    lane_descriptor,
                    git_boundary,
                    physical_snapshot=before_snapshot,
                )
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
                after_snapshot = _scan_lane_tree(lane_descriptor)
                after = _inventory(
                    lane_descriptor,
                    git_boundary,
                    physical_snapshot=after_snapshot,
                )
                _revalidate_targets(lane_descriptor, targets)
                physical_changes = _physical_snapshot_changes(
                    before_snapshot, after_snapshot
                )
                inventory_coverage = [*before["paths"], *after["paths"]]
                uncovered_physical_changes = [
                    path
                    for path in physical_changes
                    if not any(
                        _path_is_within(path, inventory_path)
                        for inventory_path in inventory_coverage
                    )
                ]
                after_breaches = sorted(
                    {
                        *_persistent_breaches(after["paths"], exact, ephemeral),
                        *_persistent_breaches(
                            uncovered_physical_changes, exact, ephemeral
                        ),
                    }
                )
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
                inventory_observed = {
                    item["path"]
                    for item in after["entries"]
                    if before_entries.get(item["path"]) != item
                }
                observed_paths = sorted(
                    {
                        *inventory_observed,
                        *(
                            path
                            for path in physical_changes
                            if not any(
                                _path_is_within(path, inventory_path)
                                for inventory_path in inventory_observed
                            )
                        ),
                    }
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
