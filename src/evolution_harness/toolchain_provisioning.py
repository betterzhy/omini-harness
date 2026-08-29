from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
import tarfile
import tempfile
import unicodedata
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit
from urllib.request import urlopen

from .hashing import canonical_json_bytes, sha256_bytes
from .toolchain_profile import (
    ToolchainBinding,
    binding_path,
    directory_identity_digest,
    find_toolchain_artifact,
    find_toolchain_profile,
    load_toolchain_binding,
    verify_profile_toolchain,
)


_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
_MAX_EXTRACTED_BYTES = 128 * 1024 * 1024
_DOWNLOAD_TIMEOUT_SECONDS = 30


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


def _read_local_archive(path: Path) -> bytes:
    value = Path(path)
    if not value.is_absolute():
        raise ValueError("toolchain archive path must be absolute")
    try:
        before = value.lstat()
        if (
            value.is_symlink()
            or not stat.S_ISREG(before.st_mode)
            or value.resolve(strict=True) != value
        ):
            raise ValueError("toolchain archive path is unavailable or unsafe")
        if before.st_size > _MAX_DOWNLOAD_BYTES:
            raise ValueError("toolchain archive exceeds 64 MiB")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(value, flags)
    except OSError as exc:
        raise ValueError("toolchain archive path is unavailable or unsafe") from exc
    try:
        opened = os.fstat(descriptor)
        if _file_identity(opened) != _file_identity(before):
            raise ValueError("toolchain archive changed during reading")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, _MAX_DOWNLOAD_BYTES + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_DOWNLOAD_BYTES:
                raise ValueError("toolchain archive exceeds 64 MiB")
            chunks.append(chunk)
        after_open = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        after_path = value.lstat()
    except OSError as exc:
        raise ValueError("toolchain archive changed during reading") from exc
    if (
        _file_identity(before) != _file_identity(after_open)
        or _file_identity(before) != _file_identity(after_path)
    ):
        raise ValueError("toolchain archive changed during reading")
    return b"".join(chunks)


def _download_archive(artifact: Mapping[str, Any]) -> bytes:
    source_uri = artifact["sourceUri"]
    parsed = urlsplit(source_uri)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("toolchain artifact source URI must be fixed HTTPS")
    with urlopen(source_uri, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response:
        data = response.read(_MAX_DOWNLOAD_BYTES + 1)
    if len(data) > _MAX_DOWNLOAD_BYTES:
        raise ValueError("toolchain artifact download exceeds 64 MiB")
    return data


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
    target: Path,
    extracted_total: int,
) -> int:
    source = archive.extractfile(member)
    if source is None:
        raise ValueError("toolchain archive regular file is unavailable")
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(target, flags, 0o600)
    actual = 0
    try:
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
        source.close()
    if actual != member.size:
        raise ValueError("toolchain archive member size mismatch")
    return extracted_total


def _extract_archive(
    data: bytes, destination: Path, artifact: Mapping[str, Any]
) -> dict[str, bool]:
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            inspected, executable = _inspect_archive(
                archive, artifact["extractedRoot"]
            )
            extracted_total = 0
            for member, relative in inspected:
                target = destination.joinpath(*relative.parts)
                if not target.is_relative_to(destination):
                    raise ValueError("toolchain archive member path is unsafe")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                extracted_total = _exclusive_write_member(
                    archive, member, target, extracted_total
                )
    except (tarfile.TarError, EOFError) as exc:
        raise ValueError("toolchain archive is invalid") from exc
    return executable


def _read_regular_file(path: Path, message: str) -> bytes:
    try:
        before = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(before.st_mode):
            raise ValueError(message)
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise ValueError(message) from exc
    try:
        opened = os.fstat(descriptor)
        if _file_identity(opened) != _file_identity(before):
            raise ValueError(message)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after_open = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        after_path = path.lstat()
    except OSError as exc:
        raise ValueError(message) from exc
    if (
        _file_identity(before) != _file_identity(after_open)
        or _file_identity(before) != _file_identity(after_path)
    ):
        raise ValueError(message)
    return b"".join(chunks)


def _verify_extracted_commands(
    root: Path,
    profile: Mapping[str, Any],
    managed: Mapping[str, Mapping[str, Any]],
    artifact: Mapping[str, Any],
) -> dict[str, Path]:
    extracted = artifact.get("extractedFiles", {})
    paths: dict[str, Path] = {}
    for name, identity in managed.items():
        file_name = identity["fileName"]
        expected = extracted.get(file_name)
        if expected is None or expected != identity["sha256"]:
            raise ValueError("toolchain artifact/profile extracted identity mismatch")
        path = root / artifact["extractedRoot"] / file_name
        digest = "sha256:" + sha256_bytes(
            _read_regular_file(path, "toolchain extracted command is unavailable or unsafe")
        )
        if digest != expected:
            raise ValueError("toolchain extracted command identity mismatch")
        paths[name] = path
    return paths


def _make_tree_read_only(
    root: Path, executable: Mapping[str, bool], command_paths: Mapping[str, Path]
) -> None:
    forced_executables = {path.relative_to(root).as_posix() for path in command_paths.values()}
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            path.chmod(0o555)
        else:
            relative = path.relative_to(root).as_posix()
            path.chmod(0o555 if executable.get(relative, False) or relative in forced_executables else 0o444)
    root.chmod(0o555)


def _remove_temp_tree(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), reverse=True):
        try:
            path.chmod(0o700 if path.is_dir() else 0o600)
        except OSError:
            pass
    try:
        root.chmod(0o700)
    except OSError:
        pass
    shutil.rmtree(root)


def _ensure_directory(path: Path, boundary: Path) -> None:
    if not path.is_absolute() or not path.is_relative_to(boundary):
        raise ValueError("toolchain managed cache path is unsafe")
    current = boundary
    for part in path.relative_to(boundary).parts:
        current = current / part
        try:
            before = current.lstat()
        except FileNotFoundError:
            try:
                current.mkdir(mode=0o755)
            except FileExistsError:
                before = current.lstat()
            else:
                before = current.lstat()
        if current.is_symlink() or not stat.S_ISDIR(before.st_mode):
            raise ValueError("toolchain managed cache path is unsafe")
        if current.resolve(strict=True) != current:
            raise ValueError("toolchain managed cache path is unsafe")


def _same_directory_identity(first: Path, second: Path) -> bool:
    try:
        return directory_identity_digest(first) == directory_identity_digest(second)
    except ValueError as exc:
        raise ValueError("toolchain managed store identity conflict") from exc


def _publish_store(temp_root: Path, final_root: Path, common_root: Path) -> bool:
    _ensure_directory(final_root.parent, common_root)
    if final_root.exists() or final_root.is_symlink():
        if not _same_directory_identity(temp_root, final_root):
            raise ValueError("toolchain managed store identity conflict")
        return False
    try:
        os.replace(temp_root, final_root)
    except OSError:
        if final_root.exists() and _same_directory_identity(temp_root, final_root):
            return False
        raise
    return True


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


def _write_binding(path: Path, record: Mapping[str, Any], common_root: Path) -> None:
    _ensure_directory(path.parent, common_root)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp-", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        data = canonical_json_bytes(record)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fchmod(descriptor, 0o444)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.chmod(0o600)
            temporary.unlink()


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
    _ensure_directory(final_root.parent, common_root)
    temp_root: Path | None = Path(
        tempfile.mkdtemp(prefix=".toolchain-provision-", dir=str(final_root.parent))
    )
    published = False
    try:
        executable = _extract_archive(data, temp_root, artifact)
        temp_commands = _verify_extracted_commands(
            temp_root, profile, managed, artifact
        )
        _make_tree_read_only(temp_root, executable, temp_commands)
        _verify_extracted_commands(temp_root, profile, managed, artifact)
        directory_identity_digest(temp_root)
        published = _publish_store(temp_root, final_root, common_root)
        if published:
            temp_root = None
        managed_paths = {
            name: final_root / artifact["extractedRoot"] / identity["fileName"]
            for name, identity in managed.items()
        }
        record = _binding_record(profile, managed_paths, explicit)
        binding = _binding_object(record)
        verify_profile_toolchain(repository_root, profile, binding)
        _write_binding(record_path, record, common_root)
        try:
            loaded = load_toolchain_binding(repository_root, profile_id)
            verified = verify_profile_toolchain(repository_root, profile, loaded)
        except Exception:
            record_path.unlink(missing_ok=True)
            raise
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
        if temp_root is not None and temp_root.exists():
            _remove_temp_tree(temp_root)


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
    if not path.exists():
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
