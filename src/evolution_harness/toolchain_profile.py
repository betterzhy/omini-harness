from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from .hashing import canonical_json_bytes, sha256_bytes
from .schema import SchemaStore


TOOLCHAIN_REGISTRY_SOURCE = "core/registries/capability-validator-toolchains.yaml"
TOOLCHAIN_REGISTRY_SCHEMA = (
    "core/schemas/capability-validator-toolchain-registry.schema.json"
)
TOOLCHAIN_BINDING_SCHEMA = (
    "core/schemas/capability-validator-toolchain-binding.schema.json"
)
MANAGED_CACHE_RELATIVE = Path(".worktrees/.capability-pack-cache")

_SYSTEM_PATH_ENTRIES = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
_JAVA_MAVEN_OFFLINE_V1_COMMAND_ORDER = ("ruby", "rg", "java", "javac", "mvn")
_JAVA_MAVEN_OFFLINE_V1_DIRECTORY_ORDER = (
    "javaHome",
    "mavenHome",
    "mavenRepository",
)
_SANITIZED_ENVIRONMENT = {
    "PATH": ":".join(_SYSTEM_PATH_ENTRIES),
    "HOME": "/var/empty",
    "XDG_CONFIG_HOME": "/var/empty",
    "LANG": "C",
    "LC_ALL": "C",
    "GIT_PAGER": "",
    "PAGER": "",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_COUNT": "9",
    "GIT_CONFIG_KEY_0": "core.fsmonitor",
    "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "core.untrackedCache",
    "GIT_CONFIG_VALUE_1": "false",
    "GIT_CONFIG_KEY_2": "maintenance.auto",
    "GIT_CONFIG_VALUE_2": "false",
    "GIT_CONFIG_KEY_3": "gc.auto",
    "GIT_CONFIG_VALUE_3": "0",
    "GIT_CONFIG_KEY_4": "fetch.writeCommitGraph",
    "GIT_CONFIG_VALUE_4": "false",
    "GIT_CONFIG_KEY_5": "core.hooksPath",
    "GIT_CONFIG_VALUE_5": "/dev/null",
    "GIT_CONFIG_KEY_6": "submodule.recurse",
    "GIT_CONFIG_VALUE_6": "false",
    "GIT_CONFIG_KEY_7": "status.submoduleSummary",
    "GIT_CONFIG_VALUE_7": "false",
    "GIT_CONFIG_KEY_8": "protocol.allow",
    "GIT_CONFIG_VALUE_8": "never",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
}


class _FrozenDict(dict[str, Any]):
    def _immutable(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("toolchain profile is immutable")

    __delitem__ = _immutable
    __ior__ = _immutable
    __setitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


@dataclass(frozen=True, slots=True)
class ToolchainBinding:
    profile_id: str
    command_paths: tuple[tuple[str, Path], ...]
    directory_paths: tuple[tuple[str, Path], ...]
    witness_digest: str


@dataclass(frozen=True, slots=True)
class VerifiedToolchain:
    profile_id: str | None
    profile_digest: str | None
    binding_witness: str | None
    command_paths: tuple[Path, ...]
    command_digests: tuple[tuple[str, str], ...]
    directory_identities: tuple[tuple[str, Path, str], ...]
    environment: Mapping[str, str]


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def profile_digest(profile: Mapping[str, Any]) -> str:
    return "sha256:" + sha256_bytes(canonical_json_bytes(_plain(profile)))


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
    )


def _read_immutable_regular_file(
    path: Path,
    *,
    message: str,
    writable_message: str | None = None,
) -> bytes:
    try:
        before = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(before.st_mode):
            raise ValueError(message)
        if writable_message is not None and (
            stat.S_IMODE(before.st_mode) & 0o222 or os.access(path, os.W_OK)
        ):
            raise ValueError(writable_message)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
    except (OSError, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise
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


def _load_registry(repository_root: Path) -> Mapping[str, Any]:
    root = Path(repository_root)
    path = root / TOOLCHAIN_REGISTRY_SOURCE
    data = _read_immutable_regular_file(
        path, message="capability pack toolchain registry is unavailable or unsafe"
    )
    try:
        loaded = yaml.safe_load(data.decode("utf-8", "strict"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("capability pack toolchain registry is invalid") from exc
    SchemaStore(root).validate(TOOLCHAIN_REGISTRY_SCHEMA, loaded)
    return loaded


def _find_artifact_in_registry(
    registry: Mapping[str, Any], artifact_id: str, expected_digest: str
) -> Mapping[str, Any]:
    matches = [
        artifact
        for artifact in registry["artifacts"]
        if artifact["artifactId"] == artifact_id
    ]
    if len(matches) != 1:
        raise ValueError("capability pack toolchain artifact not found or ambiguous")
    artifact = matches[0]
    actual_digest = "sha256:" + sha256_bytes(canonical_json_bytes(artifact))
    if actual_digest != expected_digest:
        raise ValueError("capability pack toolchain artifact identity mismatch")
    return _freeze(artifact)


def _verify_managed_artifacts(
    registry: Mapping[str, Any], profile: Mapping[str, Any]
) -> None:
    for identity in profile["commands"].values():
        if identity["bindingPolicy"] == "HARNESS_MANAGED_STORE":
            _find_artifact_in_registry(
                registry, identity["artifactId"], identity["artifactDigest"]
            )


def find_toolchain_profile(
    repository_root: Path, profile_id: str
) -> tuple[Mapping[str, Any], str]:
    registry = _load_registry(repository_root)
    matches = [
        profile
        for profile in registry["profiles"]
        if profile["profileId"] == profile_id
    ]
    if len(matches) != 1:
        raise ValueError("capability pack toolchain profile not found or ambiguous")
    profile = matches[0]
    _verify_managed_artifacts(registry, profile)
    frozen = _freeze(profile)
    return frozen, profile_digest(frozen)


def load_toolchain_profile(
    repository_root: Path, profile_id: str, expected_digest: str
) -> Mapping[str, Any]:
    profile, actual_digest = find_toolchain_profile(repository_root, profile_id)
    if actual_digest != expected_digest:
        raise ValueError("capability pack toolchain profile identity mismatch")
    return profile


def find_toolchain_artifact(
    repository_root: Path, artifact_id: str, expected_digest: str
) -> Mapping[str, Any]:
    return _find_artifact_in_registry(
        _load_registry(repository_root), artifact_id, expected_digest
    )


def _git_common_repository_root(repository_root: Path) -> Path:
    supplied = Path(repository_root)
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise ValueError("capability verification repository root is unavailable") from exc
    if not root.is_dir() or root != supplied.absolute():
        raise ValueError("capability verification repository root is unavailable")
    environment = dict(_SANITIZED_ENVIRONMENT)
    try:
        checkout = subprocess.run(
            ["/usr/bin/git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout.strip()
        common = subprocess.run(
            [
                "/usr/bin/git",
                "-C",
                str(root),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("capability verification Git common root is unavailable") from exc
    if checkout != str(root):
        raise ValueError("capability verification repository root mismatch")
    common_path = Path(common)
    try:
        common_resolved = common_path.resolve(strict=True)
    except OSError as exc:
        raise ValueError("capability verification Git common root is unavailable") from exc
    if (
        common_resolved != common_path
        or common_resolved.name != ".git"
        or common_resolved.is_symlink()
        or not common_resolved.is_dir()
    ):
        raise ValueError("capability verification Git common root is unavailable")
    return common_resolved.parent


def binding_path(repository_root: Path, profile_id: str) -> Path:
    safe = hashlib.sha256(profile_id.encode("utf-8")).hexdigest()
    return (
        _git_common_repository_root(Path(repository_root))
        / MANAGED_CACHE_RELATIVE
        / "bindings"
        / f"{safe}.json"
    )


def load_toolchain_binding(repository_root: Path, profile_id: str) -> ToolchainBinding:
    path = binding_path(repository_root, profile_id)
    try:
        if path.resolve(strict=True) != path:
            raise ValueError("capability pack toolchain binding is unavailable or unsafe")
    except OSError as exc:
        raise ValueError("capability pack toolchain binding is unavailable or unsafe") from exc
    data = _read_immutable_regular_file(
        path,
        message="capability pack toolchain binding is unavailable or unsafe",
        writable_message="capability pack toolchain binding is writable",
    )
    try:
        binding = json.loads(data.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("capability pack toolchain binding is invalid") from exc
    SchemaStore(Path(repository_root)).validate(TOOLCHAIN_BINDING_SCHEMA, binding)
    if binding["profileId"] != profile_id:
        raise ValueError("capability pack toolchain binding profile mismatch")
    return ToolchainBinding(
        profile_id=profile_id,
        command_paths=tuple(
            (name, Path(value)) for name, value in binding["commands"].items()
        ),
        directory_paths=tuple(
            (name, Path(value)) for name, value in binding["directories"].items()
        ),
        witness_digest="sha256:" + sha256_bytes(canonical_json_bytes(binding)),
    )


def directory_identity_digest(root: Path) -> str:
    if (
        not root.is_absolute()
        or root.is_symlink()
        or not root.is_dir()
        or root.resolve(strict=True) != root
    ):
        raise ValueError(
            "capability pack validator toolchain directory is unavailable or unsafe"
        )
    if os.access(root, os.W_OK):
        raise ValueError("capability pack validator toolchain directory is writable")
    entries: list[dict[str, str]] = [
        {
            "path": ".",
            "type": "directory",
            "mode": format(stat.S_IMODE(root.lstat().st_mode), "04o"),
        }
    ]
    for path in sorted(
        root.rglob("*"),
        key=lambda item: item.relative_to(root).as_posix().encode("utf-8"),
    ):
        relative = path.relative_to(root).as_posix()
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode):
            raise ValueError(
                "capability pack validator toolchain directory contains symlink"
            )
        if stat.S_ISDIR(before.st_mode):
            if os.access(path, os.W_OK):
                raise ValueError(
                    "capability pack validator toolchain directory is writable"
                )
            entries.append(
                {
                    "path": relative,
                    "type": "directory",
                    "mode": format(stat.S_IMODE(before.st_mode), "04o"),
                }
            )
            continue
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(
                "capability pack validator toolchain directory contains special file"
            )
        if os.access(path, os.W_OK):
            raise ValueError("capability pack validator toolchain file is writable")
        data = path.read_bytes()
        after = path.lstat()
        identity = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
        )
        if identity != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError(
                "capability pack validator toolchain directory changed during hashing"
            )
        entries.append(
            {
                "path": relative,
                "type": "file",
                "mode": format(stat.S_IMODE(before.st_mode), "04o"),
                "sha256": sha256_bytes(data),
            }
        )
    return "sha256:" + sha256_bytes(canonical_json_bytes(entries))


def _normalized_binding_path(path: Path) -> Path:
    value = Path(path)
    try:
        before = value.lstat()
        resolved = value.resolve(strict=True)
    except OSError as exc:
        raise ValueError(
            "capability pack validator binding path is unavailable or unsafe"
        ) from exc
    if not value.is_absolute() or value.is_symlink() or resolved != value:
        raise ValueError(
            "capability pack validator binding path is unavailable or unsafe"
        )
    if not (stat.S_ISREG(before.st_mode) or stat.S_ISDIR(before.st_mode)):
        raise ValueError(
            "capability pack validator binding path is unavailable or unsafe"
        )
    return resolved


def _require_policy_containment(
    path: Path, policy: str, managed_cache: Path
) -> None:
    if policy == "HARNESS_MANAGED_STORE" and not path.is_relative_to(
        managed_cache / "store"
    ):
        raise ValueError(
            "capability pack validator binding is outside Harness managed store"
        )
    if policy == "HARNESS_MANAGED_CACHE" and not path.is_relative_to(managed_cache):
        raise ValueError(
            "capability pack validator binding is outside Harness managed cache"
        )


def _verify_command(path: Path, name: str, identity: Mapping[str, Any]) -> str:
    if path.name != identity["fileName"]:
        raise ValueError("capability pack validator command basename mismatch")
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise ValueError(
            "capability pack validator binding path is unavailable or unsafe"
        ) from exc
    if not stat.S_ISREG(mode):
        raise ValueError(
            "capability pack validator binding path is unavailable or unsafe"
        )
    if os.access(path, os.W_OK):
        raise ValueError("capability pack validator command is writable")
    data = _read_immutable_regular_file(
        path,
        message="capability pack validator command changed during hashing",
    )
    digest = "sha256:" + sha256_bytes(data)
    if digest != identity["sha256"]:
        raise ValueError("capability pack validator command identity mismatch")
    return digest


def _platform_identity() -> dict[str, str]:
    architecture = platform.machine().lower()
    if architecture == "aarch64":
        architecture = "arm64"
    return {"os": platform.system().lower(), "architecture": architecture}


def _java_maven_offline_command_resolution(
    profile: Mapping[str, Any],
    by_name: Mapping[str, Path],
    path_entries: tuple[str, ...],
) -> None:
    verified_directories = tuple(
        dict.fromkeys(
            str(by_name[name].parent)
            for name in _JAVA_MAVEN_OFFLINE_V1_COMMAND_ORDER
        )
    )
    effective_path = ":".join(path_entries)
    for name in _JAVA_MAVEN_OFFLINE_V1_COMMAND_ORDER:
        expected = by_name[name]
        file_name = profile["commands"][name]["fileName"]
        for directory in verified_directories:
            candidate = Path(directory) / file_name
            if candidate.exists() and candidate != expected:
                raise ValueError(
                    "capability pack validator effective command resolution mismatch"
                )
        resolved = shutil.which(file_name, path=effective_path)
        if resolved is None or Path(resolved) != expected:
            raise ValueError(
                "capability pack validator effective command resolution mismatch"
            )


def verify_profile_toolchain(
    repository_root: Path,
    profile: Mapping[str, Any],
    binding: ToolchainBinding,
) -> VerifiedToolchain:
    if _plain(profile["platform"]) != _platform_identity():
        raise ValueError("capability pack toolchain profile platform mismatch")
    if binding.profile_id != profile["profileId"]:
        raise ValueError("capability pack toolchain binding profile mismatch")
    command_bindings = dict(binding.command_paths)
    directory_bindings = dict(binding.directory_paths)
    if (
        len(command_bindings) != len(binding.command_paths)
        or len(directory_bindings) != len(binding.directory_paths)
        or set(command_bindings) != set(profile["commands"])
        or set(directory_bindings) != set(profile["directories"])
    ):
        raise ValueError("capability pack toolchain binding is incomplete")
    adapter = profile["environmentAdapter"]
    if adapter != "JAVA_MAVEN_OFFLINE_V1":
        raise ValueError(
            "capability pack validator toolchain environment adapter is unsupported"
        )

    common_root = _git_common_repository_root(Path(repository_root))
    managed_cache = common_root / MANAGED_CACHE_RELATIVE
    paths: list[Path] = []
    command_digests: list[tuple[str, str]] = []
    by_name: dict[str, Path] = {}
    for name in _JAVA_MAVEN_OFFLINE_V1_COMMAND_ORDER:
        identity = profile["commands"][name]
        if identity["bindingPolicy"] == "HARNESS_MANAGED_STORE":
            find_toolchain_artifact(
                repository_root, identity["artifactId"], identity["artifactDigest"]
            )
        path = _normalized_binding_path(command_bindings[name])
        _require_policy_containment(path, identity["bindingPolicy"], managed_cache)
        digest = _verify_command(path, name, identity)
        paths.append(path)
        by_name[name] = path
        command_digests.append((name, digest))

    directories: dict[str, Path] = {}
    directory_identities: list[tuple[str, Path, str]] = []
    for name in _JAVA_MAVEN_OFFLINE_V1_DIRECTORY_ORDER:
        identity = profile["directories"][name]
        path = _normalized_binding_path(directory_bindings[name])
        _require_policy_containment(path, identity["bindingPolicy"], managed_cache)
        digest = directory_identity_digest(path)
        if digest != identity["sha256"]:
            raise ValueError(
                "capability pack validator toolchain directory identity mismatch"
            )
        directories[name] = path
        directory_identities.append((name, path, digest))

    java = by_name["java"]
    javac = by_name["javac"]
    mvn = by_name["mvn"]
    repository = directories["mavenRepository"]
    if (
        java.parent.parent != directories["javaHome"]
        or javac.parent.parent != directories["javaHome"]
    ):
        raise ValueError("capability pack validator Java home identity mismatch")
    if mvn.parent.parent != directories["mavenHome"]:
        raise ValueError("capability pack validator Maven home identity mismatch")
    if repository.name != "repository" or repository.parent.name != ".m2":
        raise ValueError("capability pack validator Maven repository identity mismatch")
    host_home = repository.parent.parent
    if (
        not host_home.is_absolute()
        or host_home.is_symlink()
        or not host_home.is_dir()
        or host_home.resolve(strict=True) != host_home
    ):
        raise ValueError("capability pack validator host HOME is unavailable or unsafe")

    environment = dict(_SANITIZED_ENVIRONMENT)
    path_entries = tuple(
        dict.fromkeys(
            [str(path.parent) for path in paths] + list(_SYSTEM_PATH_ENTRIES)
        )
    )
    _java_maven_offline_command_resolution(profile, by_name, path_entries)
    environment["PATH"] = ":".join(path_entries)
    environment["HOME"] = str(host_home)
    environment["JAVA_HOME"] = str(directories["javaHome"])
    environment["LANG"] = "en_US.UTF-8"
    environment["LC_ALL"] = "en_US.UTF-8"
    return VerifiedToolchain(
        profile_id=profile["profileId"],
        profile_digest=profile_digest(profile),
        binding_witness=binding.witness_digest,
        command_paths=tuple(paths),
        command_digests=tuple(command_digests),
        directory_identities=tuple(directory_identities),
        environment=MappingProxyType(environment),
    )


def recheck_profile_toolchain(
    repository_root: Path,
    profile: Mapping[str, Any],
    binding: ToolchainBinding,
    expected: VerifiedToolchain,
) -> None:
    actual = verify_profile_toolchain(repository_root, profile, binding)
    if actual != expected:
        raise ValueError(
            "capability pack validator toolchain identity changed during candidate Gate"
        )
