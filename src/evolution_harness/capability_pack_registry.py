from __future__ import annotations

import hashlib
import os
import platform
import signal
import subprocess
import sys
import tempfile
import threading
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from types import TracebackType
from typing import Any

import yaml

from .generated import write_generated_json
from .hashing import canonical_json_bytes, sha256_bytes
from .schema import SchemaStore, SchemaValidationError
from .toolchain_profile import (
    VerifiedToolchain,
    directory_identity_digest as _directory_identity_digest,
    load_toolchain_binding,
    load_toolchain_profile,
    verify_profile_toolchain,
)


_REGISTRATION_SCHEMA = "core/schemas/capability-pack-registration.schema.json"
_MANIFEST_SCHEMA = "core/schemas/capability-pack-manifest.schema.json"
_REGISTRY_SOURCE = "core/registries/capability-packs.yaml"
CAPABILITY_PACK_VALIDATION_ABI = "v1"
_GIT_ENVIRONMENT = {
    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
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


@dataclass(frozen=True, slots=True)
class PackVerificationKey:
    capability_id: str
    registration_id: str
    digest: str


@dataclass(frozen=True, slots=True)
class VerificationStats:
    full_candidate_gate_count: int
    isolated_checkout_count: int
    toolchain_directory_digest_count: int
    verified_pack_count: int
    verified_lock_count: int
    pack_reuse_hit_count: int
    lock_reuse_hit_count: int
    source_recheck_count: int
    registration_recheck_count: int
    lock_witness_recheck_count: int
    active_use_lease_count: int
    by_pack: Mapping[str, Mapping[str, int]]
    by_lock: Mapping[str, Mapping[str, int]]


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return deepcopy(value)


@dataclass(frozen=True, slots=True)
class VerifiedCapabilityPack:
    key: PackVerificationKey
    registration: Mapping[str, Any]
    manifest: Mapping[str, Any]
    selected_entries: tuple[tuple[str, str, str, str], ...]
    verified_toolchain: VerifiedToolchain
    _checkout_root: Path
    _locator_bound_fingerprint: str
    _session: CapabilityVerificationSession
    _session_token: object

    def registration_copy(self) -> dict[str, Any]:
        return self._session._copy_verified_registration(self)

    def lock_entry_copy(self) -> dict[str, Any]:
        return self._session._copy_verified_lock_entry(self)

    def read_blob(self, relative_path: str) -> bytes:
        return self._session._read_verified_blob(self, relative_path)

    def read_blobs(self) -> dict[str, bytes]:
        return self._session._read_verified_blobs(self)

    def recheck(self) -> None:
        self._session._recheck_verified_pack(self)


@dataclass(slots=True)
class _PackFlight:
    condition: threading.Condition
    state: str = "VERIFYING"
    value: VerifiedCapabilityPack | None = None
    error: BaseException | None = None


class CapabilityVerificationSession:
    """Operation-scoped owner of verified Pack and lock contexts."""

    def __init__(
        self,
        repository_root: Path,
        *,
        allowed_capability_ids: Iterable[str],
    ) -> None:
        supplied_root = Path(repository_root)
        try:
            resolved_root = supplied_root.resolve(strict=True)
        except OSError as exc:
            raise ValueError("capability verification repository root is unavailable") from exc
        if not resolved_root.is_dir():
            raise ValueError("capability verification repository root is unavailable")
        allowed = frozenset(allowed_capability_ids)
        if any(not isinstance(value, str) or not value for value in allowed):
            raise ValueError("capability verification allowed capability ID is invalid")
        self._repository_root = resolved_root
        self._allowed_capability_ids = allowed
        self._token = object()
        self._state = "OPEN"
        self._mutex = threading.RLock()
        self._drained = threading.Condition(self._mutex)
        self._flights: dict[PackVerificationKey, _PackFlight] = {}
        self._identity_by_slot: dict[str, PackVerificationKey] = {}
        self._verified: dict[PackVerificationKey, VerifiedCapabilityPack] = {}
        self._cleanups: list[Callable[[], object]] = []
        self._active_use_lease_count = 0
        self._counts = {
            "full_candidate_gate_count": 0,
            "isolated_checkout_count": 0,
            "toolchain_directory_digest_count": 0,
            "verified_pack_count": 0,
            "verified_lock_count": 0,
            "pack_reuse_hit_count": 0,
            "lock_reuse_hit_count": 0,
            "source_recheck_count": 0,
            "registration_recheck_count": 0,
            "lock_witness_recheck_count": 0,
        }
        self._by_pack: dict[str, dict[str, int]] = {}
        self._by_lock: dict[str, dict[str, int]] = {}

    def __enter__(self) -> CapabilityVerificationSession:
        with self._mutex:
            if self._state != "OPEN":
                raise ValueError(
                    f"capability verification session is {self._state.lower()}"
                )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_type, exc, traceback
        self.close()
        return False

    @property
    def stats(self) -> VerificationStats:
        with self._mutex:
            by_pack = MappingProxyType(
                {
                    key: MappingProxyType(dict(values))
                    for key, values in self._by_pack.items()
                }
            )
            by_lock = MappingProxyType(
                {
                    key: MappingProxyType(dict(values))
                    for key, values in self._by_lock.items()
                }
            )
            return VerificationStats(
                **self._counts,
                active_use_lease_count=self._active_use_lease_count,
                by_pack=by_pack,
                by_lock=by_lock,
            )

    def _record(
        self,
        name: str,
        amount: int = 1,
        *,
        key: PackVerificationKey | None = None,
    ) -> None:
        with self._mutex:
            self._counts[name] += amount
            if key is not None:
                values = self._by_pack.setdefault(key.digest, {})
                values[name] = values.get(name, 0) + amount

    def _require_request_locked(self, repository_root: Path, capability_id: str) -> None:
        try:
            requested_root = Path(repository_root).resolve(strict=True)
        except OSError as exc:
            raise ValueError("capability verification repository root is unavailable") from exc
        if requested_root != self._repository_root:
            raise ValueError("capability verification session repository root mismatch")
        if capability_id not in self._allowed_capability_ids:
            raise ValueError(
                f"capability is not allowed by verification session: {capability_id}"
            )
        if self._state != "OPEN":
            raise ValueError(
                f"capability verification session is {self._state.lower()}"
            )

    @contextmanager
    def _operation_lease(
        self, repository_root: Path, capability_ids: Iterable[str]
    ) -> Iterator[None]:
        requested_ids = frozenset(capability_ids)
        with self._mutex:
            try:
                requested_root = Path(repository_root).resolve(strict=True)
            except OSError as exc:
                raise ValueError(
                    "capability verification repository root is unavailable"
                ) from exc
            if requested_root != self._repository_root:
                raise ValueError("capability verification session repository root mismatch")
            missing = requested_ids - self._allowed_capability_ids
            if missing:
                raise ValueError(
                    "capability is not allowed by verification session: "
                    + sorted(missing)[0]
                )
            if self._state != "OPEN":
                raise ValueError(
                    f"capability verification session is {self._state.lower()}"
                )
            self._active_use_lease_count += 1
        try:
            yield
        except BaseException as exc:
            self._poison(exc)
            raise
        else:
            with self._mutex:
                if self._state != "OPEN":
                    raise ValueError(
                        f"capability verification session is {self._state.lower()}"
                    )
        finally:
            with self._mutex:
                self._active_use_lease_count -= 1
                if self._active_use_lease_count == 0:
                    self._drained.notify_all()

    @contextmanager
    def _request_lease(
        self, repository_root: Path, capability_id: str
    ) -> Iterator[None]:
        with self._operation_lease(repository_root, {capability_id}):
            yield

    @contextmanager
    def _verified_lease(self, pack: VerifiedCapabilityPack) -> Iterator[None]:
        with self._mutex:
            if pack._session is not self or pack._session_token is not self._token:
                raise ValueError("foreign verified capability pack")
            self._require_request_locked(
                self._repository_root, pack.key.capability_id
            )
            if self._verified.get(pack.key) is not pack:
                raise ValueError("foreign or invalidated verified capability pack")
            self._active_use_lease_count += 1
        try:
            yield
        finally:
            with self._mutex:
                self._active_use_lease_count -= 1
                if self._active_use_lease_count == 0:
                    self._drained.notify_all()

    def _poison(self, error: BaseException) -> None:
        with self._mutex:
            if self._state == "OPEN":
                self._state = "FAILED"
            failed_keys: list[PackVerificationKey] = []
            for key, flight in self._flights.items():
                if flight.state == "VERIFYING":
                    flight.error = error
                    flight.condition.notify_all()
                    failed_keys.append(key)
            for key in failed_keys:
                self._flights.pop(key, None)

    def _copy_verified_registration(
        self, pack: VerifiedCapabilityPack
    ) -> dict[str, Any]:
        with self._verified_lease(pack):
            return _thaw(pack.registration)

    def _copy_verified_lock_entry(
        self, pack: VerifiedCapabilityPack
    ) -> dict[str, Any]:
        with self._verified_lease(pack):
            return {
                **_thaw(pack.registration),
                "sourceKind": "EXTERNAL_CAPABILITY_PACK",
                "registrationFingerprint": pack._locator_bound_fingerprint,
                "manifest": _thaw(pack.manifest),
            }

    def _read_verified_blob(
        self, pack: VerifiedCapabilityPack, relative_path: str
    ) -> bytes:
        with self._verified_lease(pack):
            safe_path = validate_relative_pack_path(relative_path)
            self._recheck_pack_under_lease(pack)
            _, mode, object_type, object_id = _entry_by_path(
                list(pack.selected_entries), safe_path
            )
            if mode not in {"100644", "100755"} or object_type != "blob":
                raise ValueError(
                    "capability pack requested path is not a tracked regular file"
                )
            data = _blob(pack._checkout_root, object_id)
            self._recheck_pack_under_lease(pack)
            return data

    def _read_verified_blobs(
        self, pack: VerifiedCapabilityPack
    ) -> dict[str, bytes]:
        with self._verified_lease(pack):
            self._recheck_pack_under_lease(pack)
            blobs = {
                relative: _blob(pack._checkout_root, object_id)
                for relative, _, _, object_id in pack.selected_entries
            }
            self._recheck_pack_under_lease(pack)
            return blobs

    def _recheck_pack_under_lease(self, pack: VerifiedCapabilityPack) -> None:
        try:
            _recheck_verified_pack_witness(pack)
        except BaseException as exc:
            self._poison(exc)
            raise
        self._record("registration_recheck_count", key=pack.key)
        self._record("source_recheck_count", key=pack.key)

    def _recheck_verified_pack(self, pack: VerifiedCapabilityPack) -> None:
        with self._verified_lease(pack):
            self._recheck_pack_under_lease(pack)

    def close(self) -> None:
        with self._mutex:
            if self._state == "CLOSED":
                return
            if self._state == "CLOSING":
                while self._state != "CLOSED":
                    self._drained.wait()
                return
            self._state = "CLOSING"
            for flight in self._flights.values():
                flight.condition.notify_all()
            while self._active_use_lease_count:
                self._drained.wait()
            cleanups = list(reversed(self._cleanups))
            self._cleanups.clear()
            self._verified.clear()
            self._flights.clear()
            self._identity_by_slot.clear()
        errors: list[Exception] = []
        for cleanup in cleanups:
            try:
                cleanup()
            except Exception as exc:
                errors.append(exc)
        with self._mutex:
            self._state = "CLOSED"
            self._drained.notify_all()
        if errors:
            raise ExceptionGroup(
                "capability pack retained checkout cleanup failed", errors
            )


def _run(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    input_data: bytes | None = None,
    timeout: int = 300,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            arguments,
            cwd=cwd,
            check=check,
            capture_output=True,
            env=dict(environment or _GIT_ENVIRONMENT),
            input=input_data,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"capability pack command failed: {arguments[0]}") from exc


def _run_candidate_gate(
    arguments: list[str],
    *,
    cwd: Path,
    timeout: int,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[bytes]:
    try:
        process = subprocess.Popen(
            arguments,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(environment),
            start_new_session=True,
        )
    except OSError as exc:
        raise ValueError("capability pack candidate Gate failed to start") from exc
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        raise ValueError("capability pack candidate Gate timed out") from exc
    return subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)


def _verify_legacy_validator_toolchain(
    registration: Mapping[str, Any],
) -> VerifiedToolchain:
    validator = registration["validator"]
    contract = validator.get("environmentContract", "SANITIZED")
    if contract == "SANITIZED":
        return VerifiedToolchain(
            profile_id=None,
            profile_digest=None,
            binding_witness=None,
            command_paths=(),
            command_digests=(),
            directory_identities=(),
            environment=MappingProxyType(dict(_GIT_ENVIRONMENT)),
        )
    if contract != "REGISTERED_TOOLCHAIN_OFFLINE_CACHE":
        raise ValueError("capability pack validator environment contract is unsupported")
    paths: list[Path] = []
    command_digests: list[tuple[str, str]] = []
    for command in ("ruby", "rg", "java", "javac", "mvn"):
        identity = validator["toolchain"][command]
        path = Path(identity["absolutePath"])
        if not path.is_absolute() or not path.is_file() or path.name != command:
            raise ValueError("capability pack validator toolchain path is unavailable or unsafe")
        digest = "sha256:" + sha256_bytes(path.read_bytes())
        if digest != identity["sha256"]:
            raise ValueError("capability pack validator toolchain identity mismatch")
        paths.append(path)
        command_digests.append((command, digest))
    directories: dict[str, Path] = {}
    directory_identities: list[tuple[str, Path, str]] = []
    for name in ("javaHome", "mavenHome", "mavenRepository"):
        identity = validator["toolchain"][name]
        path = Path(identity["absolutePath"])
        digest = _directory_identity_digest(path)
        if digest != identity["sha256"]:
            raise ValueError("capability pack validator toolchain directory identity mismatch")
        directories[name] = path
        directory_identities.append((name, path, digest))
    by_name = {path.name: path for path in paths}
    if by_name["java"].parent.parent != directories["javaHome"] or (
        by_name["javac"].parent.parent != directories["javaHome"]
    ):
        raise ValueError("capability pack validator Java home identity mismatch")
    if by_name["mvn"].parent.parent != directories["mavenHome"]:
        raise ValueError("capability pack validator Maven home identity mismatch")
    repository = directories["mavenRepository"]
    if repository.name != "repository" or repository.parent.name != ".m2":
        raise ValueError("capability pack validator Maven repository identity mismatch")
    if not directories["mavenHome"].is_relative_to(repository.parent):
        raise ValueError("capability pack validator Maven home is outside registered cache")
    host_home = repository.parent.parent
    if (
        not host_home.is_absolute()
        or host_home.is_symlink()
        or not host_home.is_dir()
        or host_home.resolve(strict=True) != host_home
    ):
        raise ValueError("capability pack validator host HOME is unavailable or unsafe")
    environment = dict(_GIT_ENVIRONMENT)
    path_entries = [str(path.parent) for path in paths]
    path_entries.extend(["/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    environment["PATH"] = ":".join(dict.fromkeys(path_entries))
    environment["HOME"] = str(host_home)
    environment["JAVA_HOME"] = str(directories["javaHome"])
    environment["LANG"] = "en_US.UTF-8"
    environment["LC_ALL"] = "en_US.UTF-8"
    return VerifiedToolchain(
        profile_id=None,
        profile_digest=None,
        binding_witness=None,
        command_paths=tuple(paths),
        command_digests=tuple(command_digests),
        directory_identities=tuple(directory_identities),
        environment=MappingProxyType(environment),
    )


def _verify_validator_toolchain(
    repository_root: Path,
    registration: Mapping[str, Any],
) -> VerifiedToolchain:
    contract = registration["validator"].get("environmentContract", "SANITIZED")
    if contract in {"SANITIZED", "REGISTERED_TOOLCHAIN_OFFLINE_CACHE"}:
        return _verify_legacy_validator_toolchain(registration)
    if contract != "MANAGED_TOOLCHAIN_PROFILE":
        raise ValueError("capability pack validator environment contract is unsupported")
    reference = registration["validator"]["toolchainProfile"]
    profile = load_toolchain_profile(
        repository_root, reference["profileId"], reference["profileDigest"]
    )
    binding = load_toolchain_binding(repository_root, reference["profileId"])
    return verify_profile_toolchain(repository_root, profile, binding)


def _validator_environment(
    registration: Mapping[str, Any],
    verified_toolchain: VerifiedToolchain,
) -> dict[str, str]:
    del registration
    return dict(verified_toolchain.environment)


def _recheck_validator_toolchain(
    repository_root: Path,
    registration: Mapping[str, Any],
    expected: VerifiedToolchain,
) -> None:
    actual = _verify_validator_toolchain(repository_root, registration)
    if actual != expected:
        raise ValueError(
            "capability pack validator toolchain identity changed during candidate Gate"
        )


def _git(
    source_root: Path,
    *arguments: str,
    check: bool = True,
    input_data: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return _run(
        ["git", "-C", str(source_root), *arguments],
        check=check,
        input_data=input_data,
    )


def _git_text(source_root: Path, *arguments: str) -> str:
    try:
        return _git(source_root, *arguments).stdout.decode("utf-8", "strict").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("capability pack Git output is not UTF-8") from exc


def _is_under(relative_path: str, root: str) -> bool:
    return relative_path == root or relative_path.startswith(root + "/")


def _safe_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("capability pack path is unsafe")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("capability pack path is unsafe")
    normalized = path.as_posix()
    if normalized != value:
        raise ValueError("capability pack path is unsafe")
    return normalized


def validate_relative_pack_path(value: str) -> str:
    return _safe_relative_path(value)


def _source_root(repository_path: str) -> Path:
    source = Path(repository_path)
    if not source.is_absolute() or source.is_symlink():
        raise ValueError("capability pack source root must not be a symlink or relative path")
    try:
        resolved = source.resolve(strict=True)
    except OSError as exc:
        raise ValueError("capability pack source root is unavailable") from exc
    if not resolved.is_dir() or resolved != source:
        raise ValueError("capability pack source root must not be a symlink or alias")
    if _git_text(resolved, "rev-parse", "--show-toplevel") != str(resolved):
        raise ValueError("capability pack source root is not a Git repository root")
    return resolved


def _object_exists(source: Path, object_id: str, expected_type: str) -> bool:
    completed = _git(source, "cat-file", "-t", object_id, check=False)
    return completed.returncode == 0 and completed.stdout == (expected_type + "\n").encode("ascii")


def _require_fixed_git_identity(source: Path, registration: Mapping[str, Any]) -> tuple[str, str]:
    commit = registration["source"]["commit"]
    tree = registration["source"]["tree"]
    if not _object_exists(source, commit, "commit") or not _object_exists(source, tree, "tree"):
        raise ValueError("capability pack Git object is unavailable")
    commit_tree = _git_text(source, "rev-parse", f"{commit}^{{tree}}")
    if commit_tree != tree:
        raise ValueError("capability pack commit/tree mismatch")
    if _git_text(source, "rev-parse", "HEAD") != commit:
        raise ValueError("capability pack source commit does not match checkout HEAD")
    if _git_text(source, "rev-parse", "HEAD^{tree}") != tree:
        raise ValueError("capability pack source tree does not match checkout HEAD")
    return commit, tree


def _tree_entries(source: Path, commit: str) -> list[tuple[str, str, str, str]]:
    output = _git(source, "ls-tree", "-r", "-z", commit).stdout
    entries: list[tuple[str, str, str, str]] = []
    for raw_entry in output.split(b"\0"):
        if not raw_entry:
            continue
        metadata, separator, raw_path = raw_entry.partition(b"\t")
        fields = metadata.split(b" ")
        if not separator or len(fields) != 3:
            raise ValueError("capability pack Git tree entry is malformed")
        try:
            mode = fields[0].decode("ascii", "strict")
            object_type = fields[1].decode("ascii", "strict")
            object_id = fields[2].decode("ascii", "strict")
            relative_path = raw_path.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise ValueError("capability pack Git tree entry is not UTF-8") from exc
        _safe_relative_path(relative_path)
        entries.append((relative_path, mode, object_type, object_id))
    return entries


def _blob(source: Path, object_id: str) -> bytes:
    return _git(source, "cat-file", "blob", object_id).stdout


def _entry_by_path(
    entries: list[tuple[str, str, str, str]], relative_path: str
) -> tuple[str, str, str, str]:
    matches = [entry for entry in entries if entry[0] == relative_path]
    if len(matches) != 1:
        raise ValueError(f"capability pack required tracked file is unavailable: {relative_path}")
    return matches[0]


def _manifest_from_registration(
    source: Path,
    entries: list[tuple[str, str, str, str]],
    registration: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    declaration = registration.get("contentDeclaration") if registration else None
    if declaration and declaration["kind"] == "HARNESS_DECLARED_MANIFEST":
        manifest = declaration["manifest"]
        if not isinstance(manifest, dict):
            raise ValueError("capability pack declared manifest is invalid")
    else:
        manifest_path = (
            declaration["path"]
            if declaration and declaration["kind"] == "SOURCE_TRACKED_MANIFEST"
            else "capability-pack.yaml"
        )
        _, mode, object_type, object_id = _entry_by_path(entries, manifest_path)
        if mode not in {"100644", "100755"} or object_type != "blob":
            raise ValueError("capability pack manifest is not a tracked regular file")
        try:
            manifest = yaml.safe_load(_blob(source, object_id).decode("utf-8", "strict"))
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ValueError("capability pack manifest is invalid YAML") from exc
        if not isinstance(manifest, dict):
            raise ValueError("capability pack manifest is invalid YAML")
    return manifest


def _load_manifest(
    repository_root: Path,
    source: Path,
    entries: list[tuple[str, str, str, str]],
    registration: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = _manifest_from_registration(source, entries, registration)
    try:
        SchemaStore(repository_root).validate(_MANIFEST_SCHEMA, manifest)
    except SchemaValidationError as exc:
        raise ValueError(f"capability pack manifest schema is invalid: {exc}") from exc
    return manifest


def _tracked_manifest_path(registration: Mapping[str, Any] | None) -> str | None:
    if registration is None:
        return "capability-pack.yaml"
    declaration = registration.get("contentDeclaration")
    if declaration and declaration["kind"] == "HARNESS_DECLARED_MANIFEST":
        return None
    if declaration and declaration["kind"] == "SOURCE_TRACKED_MANIFEST":
        return declaration["path"]
    return "capability-pack.yaml"


def _validate_manifest_identity(
    registration: Mapping[str, Any], manifest: Mapping[str, Any]
) -> None:
    expected = {
        "capabilityId": registration["capabilityId"],
        "version": registration["packVersion"],
        "projectPackName": registration["source"]["repositoryId"],
        "validator.kind": registration["validator"]["kind"],
        "validator.path": registration["validator"]["relativePath"],
        "validator.argumentsContract": registration["validator"]["argumentsContract"],
    }
    actual = {
        "capabilityId": manifest["capabilityId"],
        "version": manifest["version"],
        "projectPackName": manifest["projectPackName"],
        "validator.kind": manifest["validator"]["kind"],
        "validator.path": manifest["validator"]["path"],
        "validator.argumentsContract": manifest["validator"]["argumentsContract"],
    }
    if actual != expected:
        raise ValueError("capability pack manifest identity mismatch")


def _selected_entries(
    entries: list[tuple[str, str, str, str]],
    manifest: Mapping[str, Any],
    *,
    tracked_manifest_path: str | None = "capability-pack.yaml",
) -> list[tuple[str, str, str, str]]:
    roots = [_safe_relative_path(value) for value in manifest["contentRoots"]]
    excluded = [_safe_relative_path(value) for value in manifest["excludedContentRoots"]]
    selected: list[tuple[str, str, str, str]] = []
    for entry in entries:
        relative_path = entry[0]
        explicit = relative_path == "VERSION" or relative_path == tracked_manifest_path
        active = any(_is_under(relative_path, root) for root in roots) and not any(
            _is_under(relative_path, root) for root in excluded
        )
        if explicit or active:
            selected.append(entry)
    selected.sort(key=lambda entry: entry[0].encode("utf-8"))

    selected_paths = {entry[0] for entry in selected}
    required_paths = ["VERSION", manifest["skillPath"]]
    if tracked_manifest_path is not None:
        required_paths.append(tracked_manifest_path)
    for required in required_paths:
        if required not in selected_paths:
            raise ValueError(f"capability pack required active content is unavailable: {required}")
    for root in roots:
        if not any(_is_under(path, root) for path in selected_paths):
            raise ValueError(f"capability pack content root is empty: {root}")

    normalized_paths: dict[str, str] = {}
    folded_paths: dict[str, str] = {}
    for relative_path, mode, object_type, _ in selected:
        if mode == "120000":
            raise ValueError("capability pack active content contains symlink")
        if mode == "160000" or object_type == "commit":
            raise ValueError("capability pack active content contains submodule")
        if mode not in {"100644", "100755"} or object_type != "blob":
            raise ValueError("capability pack active content is not a regular file")
        normalized = unicodedata.normalize("NFC", relative_path)
        prior = normalized_paths.setdefault(normalized, relative_path)
        if prior != relative_path:
            raise ValueError("capability pack active content normalized-path collision")
        folded = normalized.casefold()
        prior_folded = folded_paths.setdefault(folded, relative_path)
        if prior_folded != relative_path:
            raise ValueError("capability pack active content case-fold collision")
    return selected


def _untracked_active_paths(source: Path, manifest: Mapping[str, Any]) -> list[str]:
    roots = list(manifest["contentRoots"])
    excluded = list(manifest["excludedContentRoots"])
    output = _git(source, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    active: list[str] = []
    for record in output.split(b"\0"):
        if not record.startswith(b"?? "):
            continue
        try:
            relative_path = record[3:].decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise ValueError("capability pack status path is not UTF-8") from exc
        if any(_is_under(relative_path, root) for root in roots) and not any(
            _is_under(relative_path, root) for root in excluded
        ):
            active.append(relative_path)
    return active


def _ignored_untracked_active_paths(
    source: Path, manifest: Mapping[str, Any]
) -> list[str]:
    roots = list(manifest["contentRoots"])
    excluded = list(manifest["excludedContentRoots"])
    output = _git(
        source,
        "status",
        "--porcelain=v1",
        "-z",
        "--ignored=matching",
        "--untracked-files=all",
    ).stdout
    active: list[str] = []
    for record in output.split(b"\0"):
        if not record.startswith(b"!! "):
            continue
        try:
            relative_path = record[3:].decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise ValueError("capability pack ignored status path is not UTF-8") from exc
        if any(_is_under(relative_path, root) for root in roots) and not any(
            _is_under(relative_path, root) for root in excluded
        ):
            active.append(relative_path)
    return active


def _require_clean_source(source: Path, manifest: Mapping[str, Any]) -> None:
    status = _git(source, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    if status:
        if _untracked_active_paths(source, manifest):
            raise ValueError("capability pack has untracked active content")
        raise ValueError("capability pack source is not clean")
    if _ignored_untracked_active_paths(source, manifest):
        raise ValueError("capability pack has ignored untracked active content")


def _require_no_hidden_index_flags(source: Path) -> None:
    output = _git(source, "ls-files", "-v", "-z").stdout
    for record in output.split(b"\0"):
        if not record:
            continue
        if len(record) < 3 or record[1:2] != b" ":
            raise ValueError("capability pack index metadata is malformed")
        if record[:1] != b"H":
            raise ValueError("capability pack source has hidden index flags")


def _revision_object_ids(source: Path, revision: str) -> set[str]:
    tree = _git_text(source, "rev-parse", f"{revision}^{{tree}}")
    object_ids = {revision, tree}
    output = _git(source, "ls-tree", "-r", "-t", "-z", revision).stdout
    for raw_entry in output.split(b"\0"):
        if not raw_entry:
            continue
        metadata, separator, _ = raw_entry.partition(b"\t")
        fields = metadata.split(b" ")
        if not separator or len(fields) != 3:
            raise ValueError("capability pack Git tree closure is malformed")
        try:
            object_ids.add(fields[2].decode("ascii", "strict"))
        except UnicodeDecodeError as exc:
            raise ValueError("capability pack Git object ID is malformed") from exc
    return object_ids


def _fixed_commit_object_ids(
    source: Path,
    commit: str,
    tree: str,
    git_history_contract: str,
) -> list[str]:
    object_ids = _revision_object_ids(source, commit)
    object_ids.add(tree)
    if git_history_contract == "CANDIDATE_PARENT_TREE":
        parent = _git_text(source, "rev-parse", f"{commit}^")
        object_ids.update(_revision_object_ids(source, parent))
    elif git_history_contract != "CANDIDATE_ONLY":
        raise ValueError("capability pack validator Git history contract is unsupported")
    return sorted(object_ids)


@contextmanager
def _isolated_fixed_checkout(
    source: Path,
    commit: str,
    tree: str,
    git_history_contract: str = "CANDIDATE_ONLY",
) -> Iterator[Path]:
    object_ids = _fixed_commit_object_ids(
        source,
        commit,
        tree,
        git_history_contract,
    )
    packed_objects = _git(
        source,
        "pack-objects",
        "--stdout",
        input_data=("\n".join(object_ids) + "\n").encode("ascii"),
    ).stdout
    if not packed_objects:
        raise ValueError("capability pack fixed object materialization is empty")

    with tempfile.TemporaryDirectory(prefix="capability-pack-fixed-checkout-") as directory:
        checkout = Path(directory) / "checkout"
        checkout.mkdir()
        _git(checkout, "init", "-q", "--template=")
        _git(checkout, "index-pack", "--stdin", input_data=packed_objects)
        if not _object_exists(checkout, commit, "commit") or not _object_exists(
            checkout, tree, "tree"
        ):
            raise ValueError("capability pack fixed object materialization is incomplete")
        _git(checkout, "update-ref", "--no-deref", "HEAD", commit)
        _git(checkout, "reset", "--hard", commit)
        if _git_text(checkout, "rev-parse", "HEAD") != commit or _git_text(
            checkout, "rev-parse", "HEAD^{tree}"
        ) != tree:
            raise ValueError("capability pack isolated checkout identity mismatch")
        yield checkout


def _digest_entries(
    source: Path, selected: list[tuple[str, str, str, str]]
) -> str:
    digest = hashlib.sha256()
    for relative_path, mode, _, object_id in selected:
        blob = _blob(source, object_id)
        fields = (
            relative_path.encode("utf-8"),
            mode.encode("ascii"),
            str(len(blob)).encode("ascii"),
            blob,
        )
        for field in fields:
            digest.update(len(field).to_bytes(8, byteorder="big"))
            digest.update(field)
    return "sha256:" + digest.hexdigest()


def compute_capability_pack_content_digest(
    source_root: Path, manifest: Mapping[str, Any]
) -> str:
    source = _source_root(str(Path(source_root)))
    commit = _git_text(source, "rev-parse", "HEAD")
    entries = _tree_entries(source, commit)
    return _digest_entries(source, _selected_entries(entries, manifest))


def load_capability_pack_registrations(repository_root: Path) -> list[dict[str, Any]]:
    root = Path(repository_root)
    path = root / _REGISTRY_SOURCE
    if path.is_symlink():
        raise ValueError("capability pack registry source must not be a symlink")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("capability pack registry source is unavailable or invalid") from exc
    if not isinstance(loaded, list) or not all(isinstance(item, dict) for item in loaded):
        raise ValueError("capability pack registry source must be a list of registrations")
    store = SchemaStore(root)
    registrations: list[dict[str, Any]] = []
    for item in loaded:
        try:
            store.validate(_REGISTRATION_SCHEMA, item)
        except SchemaValidationError as exc:
            raise ValueError(f"capability pack registration schema is invalid: {exc}") from exc
        registrations.append(dict(item))
    return registrations


def _worktree_validator_path(source: Path, relative_path: str) -> Path:
    current = source
    for part in PurePosixPath(_safe_relative_path(relative_path)).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("capability pack validator path contains symlink")
    if not current.is_file():
        raise ValueError("capability pack validator is unavailable")
    return current


def _canonical_registration_identity_record(
    registration: Mapping[str, Any],
) -> dict[str, Any]:
    source = registration["source"]
    validator = registration["validator"]
    identity = {
        "schemaVersion": registration["schemaVersion"],
        "registrationId": registration["registrationId"],
        "capabilityId": registration["capabilityId"],
        "packVersion": registration["packVersion"],
        "status": registration["status"],
        "distributionStatus": registration["distributionStatus"],
        "source": {
            "kind": source["kind"],
            "repositoryId": source["repositoryId"],
            "commit": source["commit"],
            "tree": source["tree"],
        },
        "resolvedContentDigest": registration["resolvedContentDigest"],
        "validator": {
            "kind": validator["kind"],
            "relativePath": validator["relativePath"],
            "sha256": validator["sha256"],
            "argumentsContract": validator["argumentsContract"],
            **(
                {"environmentContract": validator["environmentContract"]}
                if "environmentContract" in validator
                else {}
            ),
            **(
                {"toolchain": _thaw(validator["toolchain"])}
                if "toolchain" in validator
                else {}
            ),
            **(
                {"gitHistoryContract": validator["gitHistoryContract"]}
                if "gitHistoryContract" in validator
                else {}
            ),
            **(
                {"timeoutSeconds": validator["timeoutSeconds"]}
                if "timeoutSeconds" in validator
                else {}
            ),
        },
    }
    if "contentDeclaration" in registration:
        identity["contentDeclaration"] = _thaw(registration["contentDeclaration"])
    return identity


def _registration_fingerprint(registration: Mapping[str, Any]) -> str:
    identity = _canonical_registration_identity_record(registration)
    return "sha256:" + sha256_bytes(canonical_json_bytes(identity))


def _locator_bound_blob_access_fingerprint(
    registration: Mapping[str, Any],
) -> str:
    return "sha256:" + sha256_bytes(canonical_json_bytes(registration))


def _manifest_identity_digest(
    source: Path,
    entries: list[tuple[str, str, str, str]],
    registration: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> str:
    tracked_path = _tracked_manifest_path(registration)
    if tracked_path is None:
        data = canonical_json_bytes(manifest)
    else:
        _, _, _, object_id = _entry_by_path(entries, tracked_path)
        data = _blob(source, object_id)
    return "sha256:" + sha256_bytes(data)


def _pack_verification_key(
    registration: Mapping[str, Any],
    manifest_digest: str,
) -> PackVerificationKey:
    identity = _canonical_registration_identity_record(registration)
    fingerprint = _registration_fingerprint(registration)
    machine = unicodedata.normalize("NFKC", platform.machine()).strip().lower()
    record = {
        "validationAbi": CAPABILITY_PACK_VALIDATION_ABI,
        "canonicalRegistrationIdentity": identity,
        "registrationFingerprint": fingerprint,
        "registrationId": registration["registrationId"],
        "capabilityId": registration["capabilityId"],
        "packVersion": registration["packVersion"],
        "sourceCommit": registration["source"]["commit"],
        "sourceTree": registration["source"]["tree"],
        "resolvedContentDigest": registration["resolvedContentDigest"],
        "manifestDigest": manifest_digest,
        "validator": {
            "sha256": registration["validator"]["sha256"],
            "argumentsContract": registration["validator"]["argumentsContract"],
            "gitHistoryContract": registration["validator"].get(
                "gitHistoryContract", "CANDIDATE_ONLY"
            ),
            "environmentContract": registration["validator"].get(
                "environmentContract", "SANITIZED"
            ),
            "timeoutSeconds": registration["validator"].get("timeoutSeconds", 300),
            "toolchain": registration["validator"].get("toolchain"),
        },
        "platform": {
            "osName": os.name,
            "sysPlatform": sys.platform,
            "machine": machine,
        },
    }
    return PackVerificationKey(
        capability_id=registration["capabilityId"],
        registration_id=registration["registrationId"],
        digest="sha256:" + sha256_bytes(canonical_json_bytes(record)),
    )


def _prepare_pack_snapshot(
    repository_root: Path,
    registration: Mapping[str, Any],
) -> tuple[
    PackVerificationKey,
    Path,
    str,
    str,
    list[tuple[str, str, str, str]],
    dict[str, Any],
    list[tuple[str, str, str, str]],
    str,
]:
    source = _source_root(registration["source"]["repositoryPath"])
    commit, tree = _require_fixed_git_identity(source, registration)
    entries = _tree_entries(source, commit)
    manifest = _load_manifest(repository_root, source, entries, registration)
    _validate_manifest_identity(registration, manifest)
    selected = _selected_entries(
        entries,
        manifest,
        tracked_manifest_path=_tracked_manifest_path(registration),
    )
    manifest_digest = _manifest_identity_digest(
        source, entries, registration, manifest
    )
    key = _pack_verification_key(registration, manifest_digest)
    locator_fingerprint = _locator_bound_blob_access_fingerprint(registration)
    return (
        key,
        source,
        commit,
        tree,
        entries,
        manifest,
        selected,
        locator_fingerprint,
    )


def _selected_registration(
    repository_root: Path,
    capability_id: str,
    *,
    registration_id: str | None = None,
    expected_locator_fingerprint: str | None = None,
    active_only: bool,
) -> dict[str, Any]:
    matches = [
        registration
        for registration in load_capability_pack_registrations(repository_root)
        if registration["capabilityId"] == capability_id
        and (registration_id is None or registration["registrationId"] == registration_id)
        and (not active_only or registration["status"] == "ACTIVE")
    ]
    if expected_locator_fingerprint is not None:
        exact = [
            registration
            for registration in matches
            if _locator_bound_blob_access_fingerprint(registration)
            == expected_locator_fingerprint
        ]
        if exact:
            return exact[0]
    if len(matches) != 1:
        if active_only and not matches:
            raise KeyError(
                "active capability pack registration not found or ambiguous: "
                + capability_id
            )
        if active_only:
            raise ValueError(f"duplicate active capability pack ID: {capability_id}")
        raise ValueError(
            f"capability pack registration not found or ambiguous: {capability_id}"
        )
    return matches[0]


def _assert_pack_source_content(
    source: Path,
    registration: Mapping[str, Any],
    manifest: Mapping[str, Any],
    entries: list[tuple[str, str, str, str]],
    selected: list[tuple[str, str, str, str]],
) -> None:
    _require_no_hidden_index_flags(source)
    _require_clean_source(source, manifest)
    content_digest = _digest_entries(source, selected)
    if content_digest != registration["resolvedContentDigest"]:
        raise ValueError("capability pack content identity mismatch")

    validator_relative = registration["validator"]["relativePath"]
    _, validator_mode, validator_type, validator_object = _entry_by_path(
        entries, validator_relative
    )
    if validator_mode != "100755" or validator_type != "blob":
        raise ValueError("capability pack validator is not a tracked executable regular file")
    validator_digest = "sha256:" + sha256_bytes(_blob(source, validator_object))
    if validator_digest != registration["validator"]["sha256"]:
        raise ValueError("capability pack validator identity mismatch")


def _recheck_verified_pack_witness(pack: VerifiedCapabilityPack) -> None:
    root = pack._session._repository_root
    registrations = load_capability_pack_registrations(root)
    if pack.registration["status"] == "ACTIVE":
        active_matches = [
            item
            for item in registrations
            if item["capabilityId"] == pack.key.capability_id
            and item["status"] == "ACTIVE"
        ]
        if len(active_matches) > 1:
            raise ValueError(
                f"duplicate active capability pack ID: {pack.key.capability_id}"
            )
        if not active_matches:
            raise ValueError("capability pack active registration identity drift")
    identity_matches = [
        item
        for item in registrations
        if item["capabilityId"] == pack.key.capability_id
        and item["registrationId"] == pack.key.registration_id
    ]
    if len(identity_matches) != 1:
        raise ValueError(
            "capability pack registration not found or ambiguous: "
            + pack.key.capability_id
        )
    registration = identity_matches[0]
    if _registration_fingerprint(registration) != _registration_fingerprint(
        pack.registration
    ):
        raise ValueError("capability pack registration identity drift")
    if (
        _locator_bound_blob_access_fingerprint(registration)
        != pack._locator_bound_fingerprint
    ):
        raise ValueError("capability pack source locator identity drift")
    (
        key,
        source,
        _commit,
        _tree,
        entries,
        manifest,
        selected,
        _locator,
    ) = _prepare_pack_snapshot(root, registration)
    if key != pack.key:
        raise ValueError("capability pack verification identity drift")
    if manifest != _thaw(pack.manifest):
        raise ValueError("capability pack manifest provenance drift")
    if tuple(selected) != pack.selected_entries:
        raise ValueError("capability pack selected object identity drift")
    _assert_pack_source_content(source, registration, manifest, entries, selected)


def _materialize_verified_capability_pack(
    session: CapabilityVerificationSession,
    repository_root: Path,
    registration: dict[str, Any],
    prepared: tuple[
        PackVerificationKey,
        Path,
        str,
        str,
        list[tuple[str, str, str, str]],
        dict[str, Any],
        list[tuple[str, str, str, str]],
        str,
    ],
) -> tuple[VerifiedCapabilityPack, Callable[[], object]]:
    (
        key,
        source,
        commit,
        tree,
        entries,
        manifest,
        selected,
        locator_fingerprint,
    ) = prepared
    _assert_pack_source_content(source, registration, manifest, entries, selected)
    toolchain = _verify_validator_toolchain(repository_root, registration)
    session._record(
        "toolchain_directory_digest_count",
        len(toolchain.directory_identities),
        key=key,
    )

    checkout_owner = _isolated_fixed_checkout(
        source,
        commit,
        tree,
        registration["validator"].get("gitHistoryContract", "CANDIDATE_ONLY"),
    )
    checkout = checkout_owner.__enter__()
    session._record("isolated_checkout_count", key=key)
    retained = False
    try:
        _require_no_hidden_index_flags(checkout)
        _require_clean_source(checkout, manifest)
        validator_relative = registration["validator"]["relativePath"]
        validator_path = _worktree_validator_path(checkout, validator_relative)
        executed_validator_digest = "sha256:" + sha256_bytes(validator_path.read_bytes())
        if executed_validator_digest != registration["validator"]["sha256"]:
            raise ValueError("capability pack executed validator identity mismatch")
        session._record("full_candidate_gate_count", key=key)
        completed = _run_candidate_gate(
            ["bash", str(validator_path), commit, tree],
            cwd=checkout,
            timeout=registration["validator"].get("timeoutSeconds", 300),
            environment=_validator_environment(registration, toolchain),
        )
        if completed.returncode != 0:
            raise ValueError("capability pack candidate Gate failed")
        if "sha256:" + sha256_bytes(validator_path.read_bytes()) != executed_validator_digest:
            raise ValueError("capability pack validator changed during candidate Gate")
        session._record(
            "toolchain_directory_digest_count",
            len(toolchain.directory_identities),
            key=key,
        )
        _recheck_validator_toolchain(repository_root, registration, toolchain)
        _require_fixed_git_identity(checkout, registration)
        _require_no_hidden_index_flags(checkout)
        _require_clean_source(checkout, manifest)

        _require_fixed_git_identity(source, registration)
        _require_no_hidden_index_flags(source)
        _require_clean_source(source, manifest)
        pack = VerifiedCapabilityPack(
            key=key,
            registration=_freeze(deepcopy(registration)),
            manifest=_freeze(deepcopy(manifest)),
            selected_entries=tuple(selected),
            verified_toolchain=toolchain,
            _checkout_root=checkout,
            _locator_bound_fingerprint=locator_fingerprint,
            _session=session,
            _session_token=session._token,
        )
        _recheck_verified_pack_witness(pack)
        session._record("registration_recheck_count", key=key)
        session._record("source_recheck_count", key=key)
        retained = True
        return pack, lambda: checkout_owner.__exit__(None, None, None)
    finally:
        if not retained:
            checkout_owner.__exit__(None, None, None)


def _get_verified_capability_pack(
    repository_root: Path,
    capability_id: str,
    *,
    verification_session: CapabilityVerificationSession,
    _registration: dict[str, Any] | None = None,
) -> VerifiedCapabilityPack:
    session = verification_session
    with session._request_lease(repository_root, capability_id):
        try:
            registration = (
                deepcopy(_registration)
                if _registration is not None
                else _selected_registration(
                    session._repository_root,
                    capability_id,
                    active_only=True,
                )
            )
            prepared = _prepare_pack_snapshot(session._repository_root, registration)
        except BaseException as exc:
            session._poison(exc)
            raise
        key = prepared[0]
        slot = key.capability_id
        owner = False
        with session._mutex:
            if session._state != "OPEN":
                raise ValueError(
                    f"capability verification session is {session._state.lower()}"
                )
            prior = session._identity_by_slot.get(slot)
            if prior is not None and prior != key:
                error = ValueError(
                    "capability pack identity changed within verification session"
                )
                session._poison(error)
                raise error
            session._identity_by_slot.setdefault(slot, key)
            flight = session._flights.get(key)
            if flight is None:
                flight = _PackFlight(threading.Condition(session._mutex))
                session._flights[key] = flight
                owner = True
            else:
                while flight.state == "VERIFYING" and session._state == "OPEN":
                    flight.condition.wait()
                if flight.error is not None:
                    raise flight.error
                if flight.state != "VERIFIED" or flight.value is None:
                    raise ValueError(
                        f"capability verification session is {session._state.lower()}"
                    )
                pack = flight.value
        if not owner:
            session._recheck_pack_under_lease(pack)
            session._record("pack_reuse_hit_count", key=key)
            return pack
        try:
            pack, cleanup = _materialize_verified_capability_pack(
                session, session._repository_root, registration, prepared
            )
        except BaseException as exc:
            session._poison(exc)
            raise
        publish_error: BaseException | None = None
        with session._mutex:
            if session._state != "OPEN":
                publish_error = ValueError(
                    f"capability verification session is {session._state.lower()}"
                )
                flight.error = publish_error
                flight.condition.notify_all()
            else:
                session._cleanups.append(cleanup)
                session._verified[key] = pack
                flight.value = pack
                flight.state = "VERIFIED"
                session._counts["verified_pack_count"] += 1
                values = session._by_pack.setdefault(key.digest, {})
                values["verified_pack_count"] = values.get("verified_pack_count", 0) + 1
                flight.condition.notify_all()
        if publish_error is not None:
            cleanup()
            raise publish_error
        return pack


def _validate_registration(
    repository_root: Path, registration: dict[str, Any]
) -> dict[str, Any]:
    with CapabilityVerificationSession(
        repository_root,
        allowed_capability_ids={registration["capabilityId"]},
    ) as session:
        pack = _get_verified_capability_pack(
            repository_root,
            registration["capabilityId"],
            verification_session=session,
            _registration=registration,
        )
        return pack.registration_copy()


def _reject_duplicate_active_ids(entries: list[dict[str, Any]]) -> None:
    active_ids: set[str] = set()
    for entry in entries:
        if entry["status"] != "ACTIVE":
            continue
        capability_id = entry["capabilityId"]
        if capability_id in active_ids:
            raise ValueError(f"duplicate active capability pack ID: {capability_id}")
        active_ids.add(capability_id)
    registration_ids: set[str] = set()
    for entry in entries:
        registration_id = entry["registrationId"]
        if registration_id in registration_ids:
            raise ValueError(f"duplicate capability pack registration ID: {registration_id}")
        registration_ids.add(registration_id)


def _canonical_registry_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    source = entry["source"]
    return {
        **entry,
        "source": {
            key: value
            for key, value in source.items()
            if key != "repositoryPath"
        },
    }


def build_capability_pack_registry(
    repository_root: Path,
    *,
    write: bool = False,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:
    root = Path(repository_root)
    registrations = load_capability_pack_registrations(root)
    capability_counts: dict[str, int] = {}
    for registration in registrations:
        capability_id = registration["capabilityId"]
        capability_counts[capability_id] = capability_counts.get(capability_id, 0) + 1

    def build(session: CapabilityVerificationSession) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        for item in registrations:
            capability_id = item["capabilityId"]
            if capability_counts[capability_id] > 1:
                with CapabilityVerificationSession(
                    root, allowed_capability_ids={capability_id}
                ) as child:
                    pack = _get_verified_capability_pack(
                        root,
                        capability_id,
                        verification_session=child,
                        _registration=item,
                    )
                    entries.append(pack.registration_copy())
                continue
            pack = _get_verified_capability_pack(
                root,
                capability_id,
                verification_session=session,
                _registration=item,
            )
            entries.append(pack.registration_copy())
        _reject_duplicate_active_ids(entries)
        entries.sort(key=lambda entry: entry["registrationId"])
        canonical_entries = [_canonical_registry_entry(entry) for entry in entries]
        result = {
            "schemaVersion": "capability-pack-registry/v1",
            "sourceRevision": "content-sha256:"
            + sha256_bytes(canonical_json_bytes(canonical_entries)),
            "entries": entries,
        }
        if write:
            write_generated_json(
                root / "generated/registries/capability-pack-registry.json", result
            )
        return result

    if verification_session is None:
        with CapabilityVerificationSession(
            root,
            allowed_capability_ids={
                registration["capabilityId"] for registration in registrations
            },
        ) as private_session:
            with private_session._operation_lease(root, capability_counts):
                return build(private_session)
    with verification_session._operation_lease(root, capability_counts):
        return build(verification_session)


def get_registered_capability_pack(
    repository_root: Path,
    capability_id: str,
    *,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:
    root = Path(repository_root)
    if verification_session is None:
        with CapabilityVerificationSession(
            root, allowed_capability_ids={capability_id}
        ) as private_session:
            pack = _get_verified_capability_pack(
                root,
                capability_id,
                verification_session=private_session,
            )
            return pack.registration_copy()
    pack = _get_verified_capability_pack(
        root,
        capability_id,
        verification_session=verification_session,
    )
    return pack.registration_copy()


def _registration_record(registration: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "schemaVersion",
        "registrationId",
        "capabilityId",
        "packVersion",
        "status",
        "distributionStatus",
        "source",
        "resolvedContentDigest",
        "validator",
    )
    optional = ("contentDeclaration",)
    allowed = set(required) | set(optional) | {
        "sourceKind",
        "registrationFingerprint",
        "manifest",
    }
    keys = set(registration)
    if not set(required).issubset(keys) or not keys.issubset(allowed):
        raise ValueError("capability pack registration identity is incomplete")
    try:
        return {
            key: registration[key]
            for key in required + optional
            if key in registration
        }
    except KeyError as exc:
        raise ValueError("capability pack registration identity is incomplete") from exc


def _registered_pack_snapshot(
    registration: Mapping[str, Any],
) -> tuple[dict[str, Any], Path, str, list[tuple[str, str, str, str]]]:
    record = _registration_record(registration)
    expected_fingerprint = "sha256:" + sha256_bytes(canonical_json_bytes(record))
    if registration.get("registrationFingerprint") != expected_fingerprint:
        raise ValueError("capability pack registration fingerprint mismatch")

    source = _source_root(record["source"]["repositoryPath"])
    commit, tree = _require_fixed_git_identity(source, record)
    entries = _tree_entries(source, commit)
    manifest = _manifest_from_registration(source, entries, record)
    if manifest != registration.get("manifest"):
        raise ValueError("capability pack locked manifest provenance mismatch")
    _validate_manifest_identity(record, manifest)
    selected = _selected_entries(
        entries,
        manifest,
        tracked_manifest_path=_tracked_manifest_path(record),
    )
    if _digest_entries(source, selected) != record["resolvedContentDigest"]:
        raise ValueError("capability pack content identity mismatch")

    validator_path = record["validator"]["relativePath"]
    validator_entry = _entry_by_path(entries, validator_path)
    if validator_entry[1] != "100755" or validator_entry[2] != "blob":
        raise ValueError("capability pack validator is not a tracked executable regular file")
    validator_digest = "sha256:" + sha256_bytes(_blob(source, validator_entry[3]))
    if validator_digest != record["validator"]["sha256"]:
        raise ValueError("capability pack validator identity mismatch")

    _require_no_hidden_index_flags(source)
    _require_clean_source(source, manifest)
    return record, source, tree, selected


def _recheck_registered_pack_snapshot(
    record: Mapping[str, Any], source: Path, tree: str, manifest: Mapping[str, Any]
) -> None:
    _require_fixed_git_identity(source, record)
    _require_no_hidden_index_flags(source)
    _require_clean_source(source, manifest)
    if tree != record["source"]["tree"]:
        raise ValueError("capability pack source tree drift")


def read_registered_pack_blob(
    registration: Mapping[str, Any], relative_path: str
) -> bytes:
    safe_path = validate_relative_pack_path(relative_path)
    record, source, tree, selected = _registered_pack_snapshot(registration)
    _, mode, object_type, object_id = _entry_by_path(selected, safe_path)
    if mode not in {"100644", "100755"} or object_type != "blob":
        raise ValueError("capability pack requested path is not a tracked regular file")
    data = _blob(source, object_id)
    _recheck_registered_pack_snapshot(record, source, tree, registration["manifest"])
    return data


def read_registered_pack_blobs(
    registration: Mapping[str, Any],
) -> dict[str, bytes]:
    record, source, tree, selected = _registered_pack_snapshot(registration)
    blobs = {relative: _blob(source, object_id) for relative, _, _, object_id in selected}
    _recheck_registered_pack_snapshot(record, source, tree, registration["manifest"])
    return blobs
