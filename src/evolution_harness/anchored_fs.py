from __future__ import annotations

import errno
import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .paths import PathBoundaryError, safe_relative_path


class AnchoredPathError(RuntimeError):
    pass


class AnchoredPathMissing(AnchoredPathError):
    pass


_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class AnchoredRoot:
    """Filesystem operations anchored to one already-open directory inode."""

    def __init__(self, root: Path):
        path = Path(root)
        try:
            descriptor = os.open(path, _DIRECTORY_FLAGS)
        except OSError as exc:
            raise AnchoredPathError(f"anchored root is unsafe: {path}") from exc
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise AnchoredPathError(f"anchored root is not a directory: {path}")
        self.root = path
        self._descriptor = descriptor

    def close(self) -> None:
        if self._descriptor >= 0:
            os.close(self._descriptor)
            self._descriptor = -1

    def __enter__(self) -> AnchoredRoot:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @staticmethod
    def _parts(relative: str) -> tuple[str, ...]:
        try:
            return safe_relative_path(relative, label="anchored path").parts
        except PathBoundaryError as exc:
            raise AnchoredPathError(str(exc)) from exc

    @contextmanager
    def _parent(self, relative: str, *, create: bool = False) -> Iterator[tuple[int, str]]:
        parts = self._parts(relative)
        current = os.dup(self._descriptor)
        try:
            for part in parts[:-1]:
                try:
                    following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(part, mode=0o755, dir_fd=current)
                    os.fsync(current)
                    following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
                except OSError as exc:
                    raise AnchoredPathError(f"anchored path parent is unsafe: {relative}") from exc
                os.close(current)
                current = following
            yield current, parts[-1]
        except FileNotFoundError as exc:
            raise AnchoredPathMissing(f"anchored path parent is missing: {relative}") from exc
        finally:
            os.close(current)

    def lstat(self, relative: str) -> os.stat_result | None:
        try:
            with self._parent(relative) as (parent, name):
                return os.stat(name, dir_fd=parent, follow_symlinks=False)
        except (AnchoredPathMissing, FileNotFoundError):
            return None

    def exists(self, relative: str) -> bool:
        return self.lstat(relative) is not None

    def is_file(self, relative: str) -> bool:
        result = self.lstat(relative)
        return result is not None and stat.S_ISREG(result.st_mode)

    def is_dir(self, relative: str) -> bool:
        result = self.lstat(relative)
        return result is not None and stat.S_ISDIR(result.st_mode)

    def mkdirs(self, relative: str, *, mode: int = 0o755) -> None:
        parts = self._parts(relative)
        current = os.dup(self._descriptor)
        try:
            for part in parts:
                try:
                    following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
                except FileNotFoundError:
                    os.mkdir(part, mode=mode, dir_fd=current)
                    os.fsync(current)
                    following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
                except OSError as exc:
                    raise AnchoredPathError(f"anchored directory is unsafe: {relative}") from exc
                os.close(current)
                current = following
        finally:
            os.close(current)

    def mkdir_new(self, relative: str, *, mode: int = 0o755) -> None:
        with self._parent(relative, create=True) as (parent, name):
            try:
                os.mkdir(name, mode=mode, dir_fd=parent)
                os.fsync(parent)
            except OSError as exc:
                raise AnchoredPathError(f"anchored directory already exists or is unsafe: {relative}") from exc

    def read_bytes(self, relative: str) -> bytes:
        with self._parent(relative) as (parent, name):
            try:
                descriptor = os.open(name, os.O_RDONLY | _NOFOLLOW, dir_fd=parent)
            except OSError as exc:
                raise AnchoredPathError(f"anchored file is unsafe or missing: {relative}") from exc
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise AnchoredPathError(f"anchored path is not a regular file: {relative}")
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(descriptor, 1024 * 1024)
                    if not chunk:
                        return b"".join(chunks)
                    chunks.append(chunk)
            finally:
                os.close(descriptor)

    def write_bytes(self, relative: str, data: bytes, *, create_parents: bool = True) -> None:
        with self._parent(relative, create=create_parents) as (parent, name):
            current = None
            try:
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            if current is not None and (stat.S_ISLNK(current.st_mode) or stat.S_ISDIR(current.st_mode)):
                raise AnchoredPathError(f"anchored destination is unsafe: {relative}")
            temporary = f".{name}.tmp-{uuid.uuid4().hex}"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW
            descriptor = -1
            try:
                descriptor = os.open(temporary, flags, 0o600, dir_fd=parent)
                view = memoryview(data)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = -1
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            except OSError as exc:
                raise AnchoredPathError(f"anchored atomic write failed: {relative}") from exc
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass

    def unlink(self, relative: str, *, missing_ok: bool = False) -> None:
        try:
            with self._parent(relative) as (parent, name):
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if stat.S_ISDIR(current.st_mode):
                    raise AnchoredPathError(f"anchored unlink target is a directory: {relative}")
                os.unlink(name, dir_fd=parent)
                os.fsync(parent)
        except (FileNotFoundError, AnchoredPathMissing) as exc:
            if missing_ok and (isinstance(exc, FileNotFoundError) or self.lstat(relative) is None):
                return
            raise

    def rename(self, source: str, destination: str) -> None:
        with self._parent(source) as (source_parent, source_name):
            with self._parent(destination, create=True) as (destination_parent, destination_name):
                try:
                    os.replace(
                        source_name,
                        destination_name,
                        src_dir_fd=source_parent,
                        dst_dir_fd=destination_parent,
                    )
                    os.fsync(source_parent)
                    if source_parent != destination_parent:
                        os.fsync(destination_parent)
                except OSError as exc:
                    raise AnchoredPathError(f"anchored rename failed: {source} -> {destination}") from exc

    def remove_tree(self, relative: str, *, missing_ok: bool = False) -> None:
        try:
            with self._parent(relative) as (parent, name):
                descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
                try:
                    self._remove_directory_contents(descriptor)
                finally:
                    os.close(descriptor)
                os.rmdir(name, dir_fd=parent)
                os.fsync(parent)
        except (FileNotFoundError, AnchoredPathMissing, OSError) as exc:
            if isinstance(exc, OSError) and exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise AnchoredPathError(f"anchored tree is unsafe: {relative}") from exc
            if missing_ok and (isinstance(exc, FileNotFoundError) or self.lstat(relative) is None):
                return
            raise AnchoredPathError(f"anchored tree removal failed: {relative}") from exc

    def _remove_directory_contents(self, descriptor: int) -> None:
        for name in os.listdir(descriptor):
            current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(current.st_mode):
                child = os.open(name, _DIRECTORY_FLAGS, dir_fd=descriptor)
                try:
                    self._remove_directory_contents(child)
                finally:
                    os.close(child)
                os.rmdir(name, dir_fd=descriptor)
            else:
                os.unlink(name, dir_fd=descriptor)
        os.fsync(descriptor)

    def rmdir_if_empty(self, relative: str) -> bool:
        try:
            with self._parent(relative) as (parent, name):
                descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
                try:
                    if os.listdir(descriptor):
                        return False
                finally:
                    os.close(descriptor)
                os.rmdir(name, dir_fd=parent)
                os.fsync(parent)
                return True
        except (FileNotFoundError, AnchoredPathMissing):
            return False
