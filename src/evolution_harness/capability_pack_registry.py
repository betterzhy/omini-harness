from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unicodedata
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .generated import write_generated_json
from .hashing import canonical_json_bytes, sha256_bytes
from .schema import SchemaStore, SchemaValidationError


_REGISTRATION_SCHEMA = "core/schemas/capability-pack-registration.schema.json"
_MANIFEST_SCHEMA = "core/schemas/capability-pack-manifest.schema.json"
_REGISTRY_SOURCE = "core/registries/capability-packs.yaml"
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


def _run(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    input_data: bytes | None = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            arguments,
            cwd=cwd,
            check=check,
            capture_output=True,
            env=_GIT_ENVIRONMENT,
            input=input_data,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"capability pack command failed: {arguments[0]}") from exc


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


def _fixed_commit_object_ids(source: Path, commit: str, tree: str) -> list[str]:
    object_ids = {commit, tree}
    output = _git(source, "ls-tree", "-r", "-t", "-z", commit).stdout
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
    return sorted(object_ids)


@contextmanager
def _isolated_fixed_checkout(source: Path, commit: str, tree: str) -> Iterator[Path]:
    object_ids = _fixed_commit_object_ids(source, commit, tree)
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


def _validate_registration(repository_root: Path, registration: dict[str, Any]) -> dict[str, Any]:
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

    with _isolated_fixed_checkout(source, commit, tree) as checkout:
        _require_no_hidden_index_flags(checkout)
        _require_clean_source(checkout, manifest)
        validator_path = _worktree_validator_path(checkout, validator_relative)
        executed_validator_digest = "sha256:" + sha256_bytes(validator_path.read_bytes())
        if executed_validator_digest != registration["validator"]["sha256"]:
            raise ValueError("capability pack executed validator identity mismatch")
        completed = _run(
            ["bash", str(validator_path), commit, tree],
            cwd=checkout,
            check=False,
        )
        if completed.returncode != 0:
            raise ValueError("capability pack candidate Gate failed")
        if "sha256:" + sha256_bytes(validator_path.read_bytes()) != executed_validator_digest:
            raise ValueError("capability pack validator changed during candidate Gate")
        _require_fixed_git_identity(checkout, registration)
        _require_no_hidden_index_flags(checkout)
        _require_clean_source(checkout, manifest)

    _require_fixed_git_identity(source, registration)
    _require_no_hidden_index_flags(source)
    _require_clean_source(source, manifest)
    return registration


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
    repository_root: Path, *, write: bool = False
) -> dict[str, Any]:
    root = Path(repository_root)
    registrations = load_capability_pack_registrations(root)
    entries = [_validate_registration(root, item) for item in registrations]
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


def get_registered_capability_pack(
    repository_root: Path, capability_id: str
) -> dict[str, Any]:
    matches = [
        entry
        for entry in build_capability_pack_registry(repository_root)["entries"]
        if entry["capabilityId"] == capability_id and entry["status"] == "ACTIVE"
    ]
    if len(matches) != 1:
        raise KeyError(
            f"active capability pack registration not found or ambiguous: {capability_id}"
        )
    return matches[0]


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
    if set(registration) != allowed:
        raise ValueError("capability pack registration identity is incomplete")
    try:
        return {
            key: registration[key]
            for key in required + optional
            if key in registration
        }
    except KeyError as exc:
        raise ValueError("capability pack registration identity is incomplete") from exc


def read_registered_pack_blob(
    registration: Mapping[str, Any], relative_path: str
) -> bytes:
    safe_path = validate_relative_pack_path(relative_path)
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
    _, mode, object_type, object_id = _entry_by_path(entries, safe_path)
    if mode not in {"100644", "100755"} or object_type != "blob":
        raise ValueError("capability pack requested path is not a tracked regular file")
    data = _blob(source, object_id)
    _require_fixed_git_identity(source, record)
    _require_no_hidden_index_flags(source)
    _require_clean_source(source, manifest)
    if tree != record["source"]["tree"]:
        raise ValueError("capability pack source tree drift")
    return data
