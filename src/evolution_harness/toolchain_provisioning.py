from __future__ import annotations

import hashlib
import io
import os
import socket
import stat
import tarfile
import time
import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

from .hashing import canonical_json_bytes, sha256_bytes
from .toolchain_profile import (
    ToolchainBinding,
    binding_path,
    find_toolchain_artifact,
    find_toolchain_profile,
    load_toolchain_binding,
    verify_profile_toolchain,
)


_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
_MAX_EXTRACTED_BYTES = 128 * 1024 * 1024
_DOWNLOAD_TIMEOUT_SECONDS = 30
_DOWNLOAD_CHUNK_BYTES = 64 * 1024
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _provision_command(profile_id: str) -> str:
    return f"harness toolchain provision --profile {profile_id} --apply"


def missing_toolchain_binding_message(profile: Mapping[str, Any]) -> str:
    artifact_ids = sorted(
        {
            identity["artifactId"]
            for identity in profile["commands"].values()
            if identity["bindingPolicy"] == "HARNESS_MANAGED_STORE"
        }
    )
    platform = profile["platform"]
    return (
        "capability pack toolchain binding is unavailable; "
        f"profile={profile['profileId']}; "
        f"managedArtifacts={','.join(artifact_ids)}; "
        f"platform={platform['os']}/{platform['architecture']}; "
        f"provision with: {_provision_command(profile['profileId'])}"
    )


def binding_path_entry_exists(path: Path) -> bool:
    """Return true for any leaf entry or unsafe parent, including dangling links."""
    value = Path(path)
    if not value.is_absolute() or any(
        part in {"", ".", ".."} for part in value.parts[1:]
    ):
        return True
    current = os.open("/", _DIRECTORY_FLAGS)
    try:
        for part in value.parts[1:-1]:
            try:
                following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
            except FileNotFoundError:
                return False
            except OSError:
                return True
            os.close(current)
            current = following
        try:
            os.stat(value.name, dir_fd=current, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError:
            return True
        return True
    finally:
        os.close(current)


def _managed_commands(
    profile: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    managed = {
        name: identity
        for name, identity in profile["commands"].items()
        if identity["bindingPolicy"] == "HARNESS_MANAGED_STORE"
    }
    if not managed:
        raise ValueError("toolchain profile has no managed artifact to provision")
    artifact_ids = {identity["artifactId"] for identity in managed.values()}
    artifact_digests = {identity["artifactDigest"] for identity in managed.values()}
    if len(artifact_ids) != 1 or len(artifact_digests) != 1:
        raise ValueError("toolchain profile managed artifact selection is ambiguous")
    return managed


def _provision_context(
    repository_root: Path, profile_id: str
) -> tuple[
    Mapping[str, Any],
    str,
    dict[str, Mapping[str, Any]],
    Mapping[str, Any],
    Path,
    Path,
]:
    profile, profile_digest = find_toolchain_profile(repository_root, profile_id)
    managed = _managed_commands(profile)
    first = next(iter(managed.values()))
    artifact = find_toolchain_artifact(
        repository_root, first["artifactId"], first["artifactDigest"]
    )
    for identity in managed.values():
        if (
            identity["artifactId"] != artifact["artifactId"]
            or identity["artifactDigest"] != first["artifactDigest"]
        ):
            raise ValueError("toolchain profile managed artifact selection is ambiguous")
    record_path = binding_path(repository_root, profile_id)
    managed_cache = record_path.parent.parent
    artifact_key = hashlib.sha256(artifact["artifactId"].encode("utf-8")).hexdigest()
    archive_key = artifact["archiveSha256"].removeprefix("sha256:")
    store_root = managed_cache / "store" / artifact_key / archive_key
    return (
        profile,
        profile_digest,
        managed,
        artifact,
        record_path,
        store_root,
    )


def _expected_explicit_names(
    profile: Mapping[str, Any], managed: Mapping[str, Mapping[str, Any]]
) -> set[str]:
    return (set(profile["commands"]) - set(managed)) | set(profile["directories"])


def _validate_explicit_bindings(
    profile: Mapping[str, Any],
    managed: Mapping[str, Mapping[str, Any]],
    explicit_bindings: Mapping[str, Path],
) -> dict[str, Path]:
    expected = _expected_explicit_names(profile, managed)
    supplied = set(explicit_bindings)
    unknown = sorted(supplied - expected)
    if unknown:
        raise ValueError(f"unknown toolchain binding: {unknown[0]}")
    missing = sorted(expected - supplied)
    if missing:
        raise ValueError(f"toolchain binding is incomplete: missing {missing[0]}")
    normalized: dict[str, Path] = {}
    for name in sorted(expected):
        path = Path(explicit_bindings[name])
        if not path.is_absolute():
            raise ValueError(f"toolchain binding path must be absolute: {name}")
        normalized[name] = path
    return normalized


def _archive_source(archive_path: Path | None) -> str:
    return "download" if archive_path is None else "archive"


def plan_toolchain_provision(
    repository_root: Path,
    profile_id: str,
    explicit_bindings: Mapping[str, Path],
    archive_path: Path | None,
) -> dict[str, Any]:
    (
        profile,
        profile_digest,
        managed,
        artifact,
        record_path,
        store_root,
    ) = _provision_context(repository_root, profile_id)
    _validate_explicit_bindings(profile, managed, explicit_bindings)
    archive = Path(archive_path) if archive_path is not None else None
    if archive is not None and not archive.is_absolute():
        raise ValueError("toolchain archive path must be absolute")
    return {
        "apply": False,
        "profileId": profile_id,
        "profileDigest": profile_digest,
        "artifactId": artifact["artifactId"],
        "archiveSha256": artifact["archiveSha256"],
        "source": _archive_source(archive),
        "sourceUri": artifact["sourceUri"],
        "archivePath": str(archive) if archive is not None else None,
        "storePath": str(store_root),
        "bindingPath": str(record_path),
        "command": _provision_command(profile_id),
    }


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
    )


def _same_inode(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        first.st_dev,
        first.st_ino,
        stat.S_IFMT(first.st_mode),
    ) == (
        second.st_dev,
        second.st_ino,
        stat.S_IFMT(second.st_mode),
    )


def _absolute_parts(path: Path, message: str) -> tuple[str, ...]:
    value = Path(path)
    if (
        not value.is_absolute()
        or not value.parts[1:]
        or any(part in {"", ".", ".."} for part in value.parts[1:])
    ):
        raise ValueError(message)
    return value.parts[1:]


def _open_absolute_directory(path: Path, message: str) -> int:
    parts = _absolute_parts(path, message)
    current = os.open("/", _DIRECTORY_FLAGS)
    try:
        for part in parts:
            try:
                following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
            except OSError as exc:
                raise ValueError(message) from exc
            os.close(current)
            current = following
        if not stat.S_ISDIR(os.fstat(current).st_mode):
            raise ValueError(message)
        return current
    except BaseException:
        os.close(current)
        raise


def _open_relative_directory(
    root_descriptor: int,
    parts: tuple[str, ...],
    *,
    create: bool,
    message: str,
) -> int:
    if any(not part or part in {".", ".."} or "/" in part for part in parts):
        raise ValueError(message)
    current = os.dup(root_descriptor)
    try:
        for part in parts:
            try:
                following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise ValueError(message)
                created = False
                try:
                    os.mkdir(part, 0o755, dir_fd=current)
                    created = True
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise ValueError(message) from exc
                try:
                    if created:
                        os.fsync(current)
                    following = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
                except OSError as exc:
                    raise ValueError(message) from exc
            except OSError as exc:
                raise ValueError(message) from exc
            os.close(current)
            current = following
        return current
    except BaseException:
        os.close(current)
        raise


def _read_descriptor(
    descriptor: int,
    before: os.stat_result,
    message: str,
    *,
    maximum_bytes: int | None = None,
    limit_message: str | None = None,
) -> bytes:
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode) or not _same_inode(opened, before):
        raise ValueError(message)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if maximum_bytes is not None and total > maximum_bytes:
            raise ValueError(limit_message or message)
        chunks.append(chunk)
    after = os.fstat(descriptor)
    if _file_identity(opened) != _file_identity(after):
        raise ValueError(message)
    return b"".join(chunks)


def _read_local_archive(path: Path) -> bytes:
    value = Path(path)
    if not value.is_absolute():
        raise ValueError("toolchain archive path must be absolute")
    parts = _absolute_parts(
        value, "toolchain archive path is unavailable or unsafe"
    )
    parent = os.open("/", _DIRECTORY_FLAGS)
    descriptor = -1
    try:
        try:
            for part in parts[:-1]:
                following = os.open(part, _DIRECTORY_FLAGS, dir_fd=parent)
                os.close(parent)
                parent = following
            before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("toolchain archive path is unavailable or unsafe")
            if before.st_size > _MAX_DOWNLOAD_BYTES:
                raise ValueError("toolchain archive exceeds 64 MiB")
            descriptor = os.open(parts[-1], _READ_FLAGS, dir_fd=parent)
        except OSError as exc:
            raise ValueError(
                "toolchain archive path is unavailable or unsafe"
            ) from exc
        data = _read_descriptor(
            descriptor,
            before,
            "toolchain archive changed during reading",
            maximum_bytes=_MAX_DOWNLOAD_BYTES,
            limit_message="toolchain archive exceeds 64 MiB",
        )
        try:
            after_path = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("toolchain archive changed during reading") from exc
        if not _same_inode(before, after_path):
            raise ValueError("toolchain archive changed during reading")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent)
    if len(data) > _MAX_DOWNLOAD_BYTES:
        raise ValueError("toolchain archive exceeds 64 MiB")
    return data


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        raise ValueError("toolchain artifact redirect is forbidden")


def urlopen(url: str, *, timeout: float):
    return build_opener(_RejectRedirects()).open(url, timeout=timeout)


def _remaining_download_time(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError(
            "toolchain artifact download exceeded 30-second total deadline"
        )
    return remaining


def _response_socket(response) -> Any:
    candidates = (
        getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None),
        getattr(getattr(response, "fp", None), "_sock", None),
        getattr(getattr(response, "raw", None), "_sock", None),
    )
    for candidate in candidates:
        if candidate is not None and callable(getattr(candidate, "settimeout", None)):
            return candidate
    raise ValueError("toolchain artifact download transport is unavailable")


def _download_archive(artifact: Mapping[str, Any]) -> bytes:
    source_uri = artifact["sourceUri"]
    parsed = urlsplit(source_uri)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("toolchain artifact source URI must be fixed HTTPS")
    deadline = time.monotonic() + _DOWNLOAD_TIMEOUT_SECONDS
    try:
        with urlopen(source_uri, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response:
            _remaining_download_time(deadline)
            if (
                callable(getattr(response, "geturl", None))
                and response.geturl() != source_uri
            ):
                raise ValueError("toolchain artifact redirect is forbidden")
            transport = _response_socket(response)
            reader = getattr(response, "read1", None)
            if not callable(reader):
                reader = response.read
            chunks: list[bytes] = []
            total = 0
            while True:
                remaining = _remaining_download_time(deadline)
                transport.settimeout(remaining)
                chunk = reader(
                    min(_DOWNLOAD_CHUNK_BYTES, _MAX_DOWNLOAD_BYTES + 1 - total)
                )
                _remaining_download_time(deadline)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_DOWNLOAD_BYTES:
                    raise ValueError("toolchain artifact download exceeds 64 MiB")
                chunks.append(chunk)
    except (TimeoutError, socket.timeout) as exc:
        raise ValueError(
            "toolchain artifact download exceeded 30-second total deadline"
        ) from exc
    return b"".join(chunks)


def _safe_member_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    raw_parts = name.split("/")
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in raw_parts)
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("toolchain archive member path is unsafe")
    return path


def _inspect_archive(
    archive: tarfile.TarFile, extracted_root: str
) -> tuple[list[tuple[tarfile.TarInfo, PurePosixPath]], dict[str, bool]]:
    inspected: list[tuple[tarfile.TarInfo, PurePosixPath]] = []
    executable: dict[str, bool] = {}
    seen: set[str] = set()
    declared_total = 0
    for member in archive.getmembers():
        relative = _safe_member_name(member.name)
        if relative.parts[0] != extracted_root:
            raise ValueError("toolchain archive member path is outside extracted root")
        normalized = unicodedata.normalize("NFC", relative.as_posix()).casefold()
        if normalized in seen:
            raise ValueError("toolchain archive member path is duplicated")
        seen.add(normalized)
        if not (member.isdir() or member.isfile()):
            raise ValueError("toolchain archive contains link or special file")
        if member.isfile():
            if member.size < 0:
                raise ValueError("toolchain archive member size is invalid")
            declared_total += member.size
            if declared_total > _MAX_EXTRACTED_BYTES:
                raise ValueError("toolchain archive exceeds 128 MiB extracted")
            executable[relative.as_posix()] = bool(member.mode & 0o111)
        inspected.append((member, relative))
    if not inspected:
        raise ValueError("toolchain archive is empty")
    return inspected, executable


def _exclusive_write_member(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    root_descriptor: int,
    relative: PurePosixPath,
    extracted_total: int,
) -> int:
    source = archive.extractfile(member)
    if source is None:
        raise ValueError("toolchain archive regular file is unavailable")
    parent = _open_relative_directory(
        root_descriptor,
        relative.parts[:-1],
        create=True,
        message="toolchain archive extraction parent is unsafe",
    )
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(relative.name, flags, 0o600, dir_fd=parent)
    except OSError:
        os.close(parent)
        source.close()
        raise
    actual = 0
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("toolchain archive extraction target is unsafe")
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            actual += len(chunk)
            extracted_total += len(chunk)
            if actual > member.size or extracted_total > _MAX_EXTRACTED_BYTES:
                raise ValueError("toolchain archive extracted size exceeds declared limit")
            view = memoryview(chunk)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
        os.close(parent)
        source.close()
    if actual != member.size:
        raise ValueError("toolchain archive member size mismatch")
    return extracted_total


@dataclass(frozen=True, slots=True)
class _ExtractedTree:
    files: tuple[PurePosixPath, ...]
    directories: tuple[PurePosixPath, ...]
    executable: Mapping[str, bool]


def _extract_archive(
    data: bytes, destination_descriptor: int, artifact: Mapping[str, Any]
) -> _ExtractedTree:
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            inspected, executable = _inspect_archive(
                archive, artifact["extractedRoot"]
            )
            extracted_total = 0
            files: set[PurePosixPath] = set()
            directories: set[PurePosixPath] = set()
            for member, relative in inspected:
                if member.isdir():
                    directory = _open_relative_directory(
                        destination_descriptor,
                        relative.parts,
                        create=True,
                        message="toolchain archive extraction directory is unsafe",
                    )
                    os.close(directory)
                    directories.add(relative)
                    continue
                extracted_total = _exclusive_write_member(
                    archive,
                    member,
                    destination_descriptor,
                    relative,
                    extracted_total,
                )
                files.add(relative)
                for depth in range(1, len(relative.parts)):
                    directories.add(PurePosixPath(*relative.parts[:depth]))
    except (tarfile.TarError, EOFError) as exc:
        raise ValueError("toolchain archive is invalid") from exc
    return _ExtractedTree(
        files=tuple(sorted(files, key=lambda item: item.as_posix().encode("utf-8"))),
        directories=tuple(
            sorted(directories, key=lambda item: item.as_posix().encode("utf-8"))
        ),
        executable=executable,
    )


def _read_regular_file_at(
    root_descriptor: int, relative: PurePosixPath, message: str
) -> bytes:
    parent = _open_relative_directory(
        root_descriptor,
        relative.parts[:-1],
        create=False,
        message=message,
    )
    descriptor = -1
    try:
        try:
            before = os.stat(relative.name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError(message)
            descriptor = os.open(relative.name, _READ_FLAGS, dir_fd=parent)
        except OSError as exc:
            raise ValueError(message) from exc
        data = _read_descriptor(descriptor, before, message)
        try:
            after_path = os.stat(
                relative.name, dir_fd=parent, follow_symlinks=False
            )
        except OSError as exc:
            raise ValueError(message) from exc
        if not _same_inode(before, after_path):
            raise ValueError(message)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent)
    return data


def _verify_extracted_commands(
    root_descriptor: int,
    profile: Mapping[str, Any],
    managed: Mapping[str, Mapping[str, Any]],
    artifact: Mapping[str, Any],
) -> dict[str, PurePosixPath]:
    extracted = artifact.get("extractedFiles", {})
    paths: dict[str, PurePosixPath] = {}
    for name, identity in managed.items():
        file_name = identity["fileName"]
        expected = extracted.get(file_name)
        if expected is None or expected != identity["sha256"]:
            raise ValueError("toolchain artifact/profile extracted identity mismatch")
        path = PurePosixPath(artifact["extractedRoot"], file_name)
        digest = "sha256:" + sha256_bytes(
            _read_regular_file_at(
                root_descriptor,
                path,
                "toolchain extracted command is unavailable or unsafe",
            )
        )
        if digest != expected:
            raise ValueError("toolchain extracted command identity mismatch")
        paths[name] = path
    return paths


def _make_tree_read_only(
    root_descriptor: int,
    tree: _ExtractedTree,
    command_paths: Mapping[str, PurePosixPath],
) -> None:
    forced_executables = {path.as_posix() for path in command_paths.values()}
    for relative in reversed(tree.files):
        parent = _open_relative_directory(
            root_descriptor,
            relative.parts[:-1],
            create=False,
            message="toolchain extracted file parent is unsafe",
        )
        try:
            descriptor = os.open(relative.name, _READ_FLAGS, dir_fd=parent)
            try:
                mode = (
                    0o555
                    if tree.executable.get(relative.as_posix(), False)
                    or relative.as_posix() in forced_executables
                    else 0o444
                )
                os.fchmod(descriptor, mode)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            os.close(parent)
    for relative in sorted(
        tree.directories, key=lambda item: len(item.parts), reverse=True
    ):
        descriptor = _open_relative_directory(
            root_descriptor,
            relative.parts,
            create=False,
            message="toolchain extracted directory is unsafe",
        )
        try:
            os.fchmod(descriptor, 0o555)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    os.fchmod(root_descriptor, 0o555)
    os.fsync(root_descriptor)


def _directory_identity_digest_fd(root_descriptor: int) -> str:
    root = os.fstat(root_descriptor)
    if not stat.S_ISDIR(root.st_mode) or stat.S_IMODE(root.st_mode) & 0o222:
        raise ValueError("toolchain managed store identity conflict")
    entries: list[dict[str, str]] = [
        {
            "path": ".",
            "type": "directory",
            "mode": format(stat.S_IMODE(root.st_mode), "04o"),
        }
    ]

    def visit(directory_descriptor: int, prefix: PurePosixPath | None) -> None:
        for name in sorted(
            os.listdir(directory_descriptor), key=lambda item: item.encode("utf-8")
        ):
            relative = PurePosixPath(name) if prefix is None else prefix / name
            before = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode):
                raise ValueError("toolchain managed store identity conflict")
            if stat.S_ISDIR(before.st_mode):
                if stat.S_IMODE(before.st_mode) & 0o222:
                    raise ValueError("toolchain managed store identity conflict")
                child = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory_descriptor)
                try:
                    if not _same_inode(before, os.fstat(child)):
                        raise ValueError("toolchain managed store identity conflict")
                    entries.append(
                        {
                            "path": relative.as_posix(),
                            "type": "directory",
                            "mode": format(stat.S_IMODE(before.st_mode), "04o"),
                        }
                    )
                    visit(child, relative)
                finally:
                    os.close(child)
                after_path = os.stat(
                    name, dir_fd=directory_descriptor, follow_symlinks=False
                )
                if not _same_inode(before, after_path):
                    raise ValueError("toolchain managed store identity conflict")
                continue
            if not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) & 0o222:
                raise ValueError("toolchain managed store identity conflict")
            descriptor = os.open(name, _READ_FLAGS, dir_fd=directory_descriptor)
            try:
                data = _read_descriptor(
                    descriptor, before, "toolchain managed store identity conflict"
                )
                after_path = os.stat(
                    name, dir_fd=directory_descriptor, follow_symlinks=False
                )
                if not _same_inode(before, after_path):
                    raise ValueError("toolchain managed store identity conflict")
            finally:
                os.close(descriptor)
            entries.append(
                {
                    "path": relative.as_posix(),
                    "type": "file",
                    "mode": format(stat.S_IMODE(before.st_mode), "04o"),
                    "sha256": sha256_bytes(data),
                }
            )

    visit(root_descriptor, None)
    return "sha256:" + sha256_bytes(canonical_json_bytes(entries))


def _entry_lstat(parent_descriptor: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _publish_store(
    temp_descriptor: int,
    parent_descriptor: int,
    temp_name: str,
    final_name: str,
) -> int:
    temp_identity = _directory_identity_digest_fd(temp_descriptor)
    current = _entry_lstat(parent_descriptor, final_name)
    if current is not None:
        if not stat.S_ISDIR(current.st_mode):
            raise ValueError("toolchain managed store identity conflict")
        try:
            final_descriptor = os.open(
                final_name, _DIRECTORY_FLAGS, dir_fd=parent_descriptor
            )
        except OSError as exc:
            raise ValueError("toolchain managed store identity conflict") from exc
        try:
            if not _same_inode(current, os.fstat(final_descriptor)):
                raise ValueError("toolchain managed store identity conflict")
            if _directory_identity_digest_fd(final_descriptor) != temp_identity:
                raise ValueError("toolchain managed store identity conflict")
        except BaseException:
            os.close(final_descriptor)
            raise
        return final_descriptor
    os.replace(
        temp_name,
        final_name,
        src_dir_fd=parent_descriptor,
        dst_dir_fd=parent_descriptor,
    )
    installed = os.stat(
        final_name, dir_fd=parent_descriptor, follow_symlinks=False
    )
    if not _same_inode(os.fstat(temp_descriptor), installed):
        raise ValueError("toolchain managed store publication identity mismatch")
    os.fsync(parent_descriptor)
    final_descriptor = os.open(
        final_name, _DIRECTORY_FLAGS, dir_fd=parent_descriptor
    )
    if not _same_inode(installed, os.fstat(final_descriptor)):
        os.close(final_descriptor)
        raise ValueError("toolchain managed store publication identity mismatch")
    return final_descriptor


def _remove_directory_contents(descriptor: int) -> None:
    os.fchmod(descriptor, 0o700)
    for name in os.listdir(descriptor):
        current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISDIR(current.st_mode):
            child = os.open(name, _DIRECTORY_FLAGS, dir_fd=descriptor)
            try:
                _remove_directory_contents(child)
            finally:
                os.close(child)
            os.rmdir(name, dir_fd=descriptor)
        else:
            try:
                child = os.open(name, _READ_FLAGS, dir_fd=descriptor)
            except OSError:
                child = -1
            if child >= 0:
                try:
                    os.fchmod(child, 0o600)
                finally:
                    os.close(child)
            os.unlink(name, dir_fd=descriptor)


def _remove_tree_at(
    parent_descriptor: int,
    name: str,
    expected: os.stat_result,
) -> None:
    current = _entry_lstat(parent_descriptor, name)
    if current is None:
        return
    if not _same_inode(expected, current) or not stat.S_ISDIR(expected.st_mode):
        raise ValueError("toolchain temporary cleanup identity mismatch")
    descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_descriptor)
    try:
        if not _same_inode(expected, os.fstat(descriptor)):
            raise ValueError("toolchain temporary cleanup identity mismatch")
        _remove_directory_contents(descriptor)
    finally:
        os.close(descriptor)
    current = _entry_lstat(parent_descriptor, name)
    if current is None or not _same_inode(expected, current):
        raise ValueError("toolchain temporary cleanup identity mismatch")
    os.rmdir(name, dir_fd=parent_descriptor)
    os.fsync(parent_descriptor)


def _binding_record(
    profile: Mapping[str, Any],
    managed_paths: Mapping[str, Path],
    explicit_bindings: Mapping[str, Path],
) -> dict[str, Any]:
    commands = {
        name: str(managed_paths.get(name, explicit_bindings.get(name)))
        for name in profile["commands"]
    }
    directories = {
        name: str(explicit_bindings[name]) for name in profile["directories"]
    }
    return {
        "schemaVersion": "capability-validator-toolchain-binding/v1",
        "profileId": profile["profileId"],
        "commands": commands,
        "directories": directories,
    }


def _binding_object(record: Mapping[str, Any]) -> ToolchainBinding:
    return ToolchainBinding(
        profile_id=record["profileId"],
        command_paths=tuple(
            (name, Path(path)) for name, path in record["commands"].items()
        ),
        directory_paths=tuple(
            (name, Path(path)) for name, path in record["directories"].items()
        ),
        witness_digest="sha256:" + sha256_bytes(canonical_json_bytes(record)),
    )


def _rollback_binding(
    parent_descriptor: int,
    final_name: str,
    installed_descriptor: int,
    expected: os.stat_result,
) -> None:
    try:
        os.fchmod(installed_descriptor, 0o000)
        os.fsync(installed_descriptor)
    except OSError:
        pass
    current = _entry_lstat(parent_descriptor, final_name)
    if current is None:
        os.fsync(parent_descriptor)
        return
    if not _same_inode(expected, current):
        raise ValueError("toolchain binding rollback identity cannot be proven")
    os.unlink(final_name, dir_fd=parent_descriptor)
    if _entry_lstat(parent_descriptor, final_name) is not None:
        raise ValueError("toolchain binding rollback identity cannot be proven")
    os.fsync(parent_descriptor)


def _require_pinned_directory_at(
    root_descriptor: int,
    parts: tuple[str, ...],
    expected_descriptor: int,
    message: str,
) -> None:
    current = _open_relative_directory(
        root_descriptor,
        parts,
        create=False,
        message=message,
    )
    try:
        if not _same_inode(os.fstat(expected_descriptor), os.fstat(current)):
            raise ValueError(message)
    finally:
        os.close(current)


def _require_public_store_identity(
    filesystem_root_descriptor: int,
    common_root_parts: tuple[str, ...],
    common_root_descriptor: int,
    store_parent_parts: tuple[str, ...],
    store_parent_descriptor: int,
    final_name: str,
    final_descriptor: int,
) -> None:
    message = "toolchain public managed root identity changed"
    public_common = _open_relative_directory(
        filesystem_root_descriptor,
        common_root_parts,
        create=False,
        message=message,
    )
    try:
        if not _same_inode(os.fstat(common_root_descriptor), os.fstat(public_common)):
            raise ValueError(message)
        public_store_parent = _open_relative_directory(
            public_common,
            store_parent_parts,
            create=False,
            message=message,
        )
        try:
            if not _same_inode(
                os.fstat(store_parent_descriptor), os.fstat(public_store_parent)
            ):
                raise ValueError(message)
            try:
                public_final = os.open(
                    final_name, _DIRECTORY_FLAGS, dir_fd=public_store_parent
                )
            except OSError as exc:
                raise ValueError(message) from exc
            try:
                if not _same_inode(
                    os.fstat(final_descriptor), os.fstat(public_final)
                ):
                    raise ValueError(message)
            finally:
                os.close(public_final)
        finally:
            os.close(public_store_parent)
    finally:
        os.close(public_common)


def _write_binding(
    common_root_descriptor: int,
    path: Path,
    common_root: Path,
    record: Mapping[str, Any],
    verify_installed: Callable[[], Any],
    verify_public_store: Callable[[], None],
) -> Any:
    try:
        relative_parent = path.parent.relative_to(common_root).parts
    except ValueError as exc:
        raise ValueError("toolchain binding path is outside managed root") from exc
    parent = _open_relative_directory(
        common_root_descriptor,
        relative_parent,
        create=True,
        message="toolchain binding parent is unavailable or unsafe",
    )
    temporary_name = f".{path.name}.tmp-{uuid.uuid4().hex}"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = -1
    expected: os.stat_result | None = None
    replaced = False
    try:
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=parent)
        data = canonical_json_bytes(record)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fchmod(descriptor, 0o444)
        os.fsync(descriptor)
        expected = os.fstat(descriptor)
        try:
            verify_public_store()
            os.replace(
                temporary_name,
                path.name,
                src_dir_fd=parent,
                dst_dir_fd=parent,
            )
            replaced = True
            installed = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if not _same_inode(expected, installed):
                raise ValueError("toolchain binding publication identity mismatch")
            os.fsync(parent)
            verified = verify_installed()
            installed = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if not _same_inode(expected, installed):
                raise ValueError("toolchain binding publication identity mismatch")
            _require_pinned_directory_at(
                common_root_descriptor,
                relative_parent,
                parent,
                "toolchain binding parent changed during publication",
            )
            verify_public_store()
            return verified
        except BaseException as original:
            current = _entry_lstat(parent, path.name)
            installed_here = current is not None and _same_inode(expected, current)
            if replaced or installed_here:
                try:
                    _rollback_binding(parent, path.name, descriptor, expected)
                except BaseException as rollback_error:
                    raise ValueError(
                        "toolchain binding write failed and rollback cannot be proven"
                    ) from rollback_error
            raise original
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary = _entry_lstat(parent, temporary_name)
        if temporary is not None:
            if stat.S_ISREG(temporary.st_mode):
                temporary_descriptor = os.open(
                    temporary_name, _READ_FLAGS, dir_fd=parent
                )
                try:
                    os.fchmod(temporary_descriptor, 0o600)
                finally:
                    os.close(temporary_descriptor)
            os.unlink(temporary_name, dir_fd=parent)
        os.close(parent)


def _resolved_paths(verified) -> dict[str, dict[str, str]]:
    return {
        "commands": {
            name: str(path)
            for (name, _digest), path in zip(
                verified.command_digests, verified.command_paths, strict=True
            )
        },
        "directories": {
            name: str(path) for name, path, _digest in verified.directory_identities
        },
    }


def provision_toolchain(
    repository_root: Path,
    profile_id: str,
    explicit_bindings: Mapping[str, Path],
    archive_path: Path | None,
) -> dict[str, Any]:
    (
        profile,
        profile_digest,
        managed,
        artifact,
        record_path,
        final_root,
    ) = _provision_context(repository_root, profile_id)
    explicit = _validate_explicit_bindings(profile, managed, explicit_bindings)
    data = (
        _download_archive(artifact)
        if archive_path is None
        else _read_local_archive(Path(archive_path))
    )
    digest = "sha256:" + sha256_bytes(data)
    if digest != artifact["archiveSha256"]:
        raise ValueError("toolchain archive identity mismatch")

    common_root = record_path.parents[3]
    common_root_parts = _absolute_parts(
        common_root, "toolchain managed root is unavailable or unsafe"
    )
    filesystem_root_descriptor = os.open("/", _DIRECTORY_FLAGS)
    try:
        common_root_descriptor = _open_relative_directory(
            filesystem_root_descriptor,
            common_root_parts,
            create=False,
            message="toolchain managed root is unavailable or unsafe",
        )
    except BaseException:
        os.close(filesystem_root_descriptor)
        raise
    store_parent_descriptor = -1
    temp_descriptor = -1
    published_descriptor = -1
    temp_identity: os.stat_result | None = None
    temp_created = False
    temp_name = f".toolchain-provision-{uuid.uuid4().hex}"
    try:
        try:
            store_parent_parts = final_root.parent.relative_to(common_root).parts
        except ValueError as exc:
            raise ValueError("toolchain managed store is outside managed root") from exc
        store_parent_descriptor = _open_relative_directory(
            common_root_descriptor,
            store_parent_parts,
            create=True,
            message="toolchain managed store parent is unavailable or unsafe",
        )
        os.mkdir(temp_name, 0o700, dir_fd=store_parent_descriptor)
        temp_created = True
        os.fsync(store_parent_descriptor)
        temp_descriptor = os.open(
            temp_name, _DIRECTORY_FLAGS, dir_fd=store_parent_descriptor
        )
        temp_identity = os.fstat(temp_descriptor)
        extracted_tree = _extract_archive(data, temp_descriptor, artifact)
        temp_commands = _verify_extracted_commands(
            temp_descriptor, profile, managed, artifact
        )
        _make_tree_read_only(temp_descriptor, extracted_tree, temp_commands)
        _verify_extracted_commands(temp_descriptor, profile, managed, artifact)
        _directory_identity_digest_fd(temp_descriptor)
        published_descriptor = _publish_store(
            temp_descriptor,
            store_parent_descriptor,
            temp_name,
            final_root.name,
        )
        managed_paths = {
            name: final_root / artifact["extractedRoot"] / identity["fileName"]
            for name, identity in managed.items()
        }
        record = _binding_record(profile, managed_paths, explicit)
        binding = _binding_object(record)
        verify_profile_toolchain(repository_root, profile, binding)

        def verify_public_store() -> None:
            _require_public_store_identity(
                filesystem_root_descriptor,
                common_root_parts,
                common_root_descriptor,
                store_parent_parts,
                store_parent_descriptor,
                final_root.name,
                published_descriptor,
            )

        def verify_installed():
            loaded = load_toolchain_binding(repository_root, profile_id)
            return verify_profile_toolchain(repository_root, profile, loaded)

        verified = _write_binding(
            common_root_descriptor,
            record_path,
            common_root,
            record,
            verify_installed,
            verify_public_store,
        )
        return {
            "apply": True,
            "profileId": profile_id,
            "profileDigest": profile_digest,
            "artifactId": artifact["artifactId"],
            "archiveSha256": artifact["archiveSha256"],
            "bindingWitness": verified.binding_witness,
            "resolvedPaths": _resolved_paths(verified),
        }
    finally:
        try:
            if (
                store_parent_descriptor >= 0
                and temp_created
                and temp_identity is not None
            ):
                _remove_tree_at(
                    store_parent_descriptor,
                    temp_name,
                    temp_identity,
                )
        finally:
            if published_descriptor >= 0:
                os.close(published_descriptor)
            if temp_descriptor >= 0:
                os.close(temp_descriptor)
            if store_parent_descriptor >= 0:
                os.close(store_parent_descriptor)
            os.close(common_root_descriptor)
            os.close(filesystem_root_descriptor)


def toolchain_status(repository_root: Path, profile_id: str) -> dict[str, Any]:
    (
        profile,
        profile_digest,
        _managed,
        artifact,
        path,
        _store_root,
    ) = _provision_context(repository_root, profile_id)
    command = _provision_command(profile_id)
    identity = {
        "profileId": profile_id,
        "profileDigest": profile_digest,
        "artifactId": artifact["artifactId"],
        "platform": dict(artifact["platform"]),
    }
    if not binding_path_entry_exists(path):
        return {
            "status": "MISSING",
            **identity,
            "message": (
                "toolchain binding is unavailable; provision explicitly with: "
                + command
            ),
            "command": command,
        }
    try:
        binding = load_toolchain_binding(repository_root, profile_id)
        verified = verify_profile_toolchain(repository_root, profile, binding)
    except ValueError as exc:
        return {
            "status": "INVALID",
            **identity,
            "message": str(exc),
            "command": command,
        }
    return {
        "status": "READY",
        **identity,
        "bindingWitness": verified.binding_witness,
        "resolvedPaths": _resolved_paths(verified),
    }
