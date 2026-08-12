from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from .generated import deterministic_json_bytes
from .hashing import file_sha256
from .paths import PathBoundaryError, resolve_without_symlinks, resolve_within, safe_relative_path
from .projection import validate_projection_pack
from .process_lock import ProcessLockError, exclusive_process_lock, process_lock_identity
from .schema import SchemaStore


INSTALL_MANIFEST_PATH = ".agent-evolution/projection-install-manifest.json"
INSTALL_TRANSACTION_PATH = ".agent-evolution/projection-install-transaction.json"
INSTALL_BACKUP_ROOT = ".agent-evolution/projection-install-backups"
_TRANSACTION_TOKEN = re.compile(r"^[0-9a-f]{32}$")


class ProjectionInstallError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _managed_manifest(repository_root: Path, target_root: Path) -> tuple[Path, dict[str, Any] | None]:
    path = resolve_without_symlinks(target_root, INSTALL_MANIFEST_PATH, label="install manifest path")
    if not path.exists():
        return path, None
    manifest = _load_json(path)
    SchemaStore(repository_root).validate("core/schemas/projection-install-manifest.schema.json", manifest)
    return path, manifest


def _projection_inputs(
    repository_root: Path,
    pack_root: Path,
    source_root: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    repository = Path(repository_root).resolve()
    pack = Path(pack_root).resolve()
    try:
        relative = pack.relative_to(repository / "generated" / "projections")
    except ValueError as exc:
        raise ProjectionInstallError("projection pack is outside the canonical generated projections root") from exc
    if len(relative.parts) != 2:
        raise ProjectionInstallError("projection pack is outside the canonical generated projections root")
    runtime_name, project_id = relative.parts
    runtime = runtime_name.upper()
    if runtime not in {"CHATGPT", "CODEX"}:
        raise ProjectionInstallError("projection pack runtime is unsupported")
    integration_root = repository / "integrations" / project_id
    integration_control = integration_root / "control-plane"
    example_project = repository / "examples" / project_id
    project = integration_control if integration_control.is_dir() else example_project
    if not project.is_dir():
        raise ProjectionInstallError("projection pack project control plane is not registered")
    authority_snapshot = None
    if integration_control.is_dir():
        if source_root is None:
            raise ProjectionInstallError("integration projection validation requires its live source")
        from .authority import build_authority_snapshot

        authority_snapshot = build_authority_snapshot(repository, integration_root, source_root)
    try:
        manifest, resolved = validate_projection_pack(
            repository,
            project,
            pack,
            runtime=runtime,
            authority_snapshot=authority_snapshot,
        )
    except Exception as exc:
        raise ProjectionInstallError(f"projection pack is not a canonical projection: {exc}") from exc
    file_hashes = {item["path"]: item["sha256"] for item in manifest.get("generatedFiles", [])}
    inputs: list[dict[str, Any]] = []
    for skill in manifest.get("generatedSkills", []):
        raw_path = skill.get("path", "")
        try:
            relative = safe_relative_path(raw_path, label="projected skill path")
        except PathBoundaryError as exc:
            raise ProjectionInstallError(f"unsafe projected skill path: {raw_path}") from exc
        if len(relative.parts) != 3 or relative.parts[0] != "skills" or relative.parts[2] != "SKILL.md":
            raise ProjectionInstallError(f"unsafe projected skill path: {raw_path}")
        try:
            source = resolve_within(pack, relative.as_posix(), must_exist=True, label="projected skill path")
        except (PathBoundaryError, FileNotFoundError) as exc:
            raise ProjectionInstallError(f"unsafe projected skill path: {raw_path}") from exc
        expected_hash = file_hashes.get(relative.as_posix())
        if not expected_hash or file_sha256(source) != expected_hash:
            raise ProjectionInstallError(f"projected skill hash mismatch: {raw_path}")
        target_path = PurePosixPath(".agents", "skills", relative.parts[1], "SKILL.md").as_posix()
        inputs.append(
            {
                "path": target_path,
                "sourcePath": relative.as_posix(),
                "sourceSha256": expected_hash,
                "installedSha256": expected_hash,
                "capabilityId": skill["id"],
                "capabilityVersion": skill["version"],
                "capabilityContentHash": skill["contentHash"],
                "_source": source,
            }
        )
    manifest["_validatedResolvedContext"] = resolved
    manifest["_validatedIntegrationRoot"] = str(integration_root) if integration_control.is_dir() else None
    return manifest, inputs


def _persistent_manifest(projection: dict[str, Any], inputs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": "projection-install-manifest/v1",
        "sourceProjection": {
            "runtime": projection["runtime"],
            "project": projection["project"],
            "projectionType": projection["projectionType"],
            "projectionVersion": projection["projectionVersion"],
            "sourceResolutionId": projection["sourceResolutionId"],
            "capabilityLockFingerprint": projection["capabilityLockFingerprint"],
        },
        "installedFiles": [
            {key: value for key, value in item.items() if key != "_source"}
            for item in sorted(inputs, key=lambda value: value["path"])
        ],
    }


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass


def _lexical_managed_path(target: Path, relative: str, *, allow_leaf_symlink: bool = False) -> Path:
    rel = safe_relative_path(relative, label="managed transaction path")
    current = target
    for part in rel.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ProjectionInstallError(f"managed transaction parent contains symlink: {relative}")
    destination = current / rel.parts[-1]
    if destination.is_symlink() and not allow_leaf_symlink:
        raise ProjectionInstallError(f"managed transaction path contains symlink: {relative}")
    return destination


def _is_managed_skill_path(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        relative = safe_relative_path(value, label="managed skill path")
    except PathBoundaryError:
        return False
    return (
        len(relative.parts) == 4
        and relative.parts[0] == ".agents"
        and relative.parts[1] == "skills"
        and relative.parts[3] == "SKILL.md"
    )


def _validate_transaction_journal(journal: Any) -> dict[str, Any]:
    if not isinstance(journal, dict) or set(journal) != {
        "schemaVersion",
        "operation",
        "phase",
        "backupDirectory",
        "files",
        "manifest",
    }:
        raise ProjectionInstallError("invalid projection install recovery journal")
    if journal.get("schemaVersion") != "projection-install-transaction/v1":
        raise ProjectionInstallError("invalid projection install recovery journal")
    if journal.get("operation") not in {"INSTALL", "UNINSTALL"}:
        raise ProjectionInstallError("invalid projection install recovery journal")
    if journal.get("phase") not in {"PREPARED", "COMMITTED"}:
        raise ProjectionInstallError("invalid projection install recovery journal")
    backup_directory = journal.get("backupDirectory")
    if not isinstance(backup_directory, str):
        raise ProjectionInstallError("invalid projection install recovery journal")
    backup_parts = PurePosixPath(backup_directory).parts
    expected_prefix = PurePosixPath(INSTALL_BACKUP_ROOT).parts
    if (
        len(backup_parts) != len(expected_prefix) + 1
        or backup_parts[:-1] != expected_prefix
        or not _TRANSACTION_TOKEN.fullmatch(backup_parts[-1])
    ):
        raise ProjectionInstallError("invalid projection install recovery journal")
    files = journal.get("files")
    if not isinstance(files, list):
        raise ProjectionInstallError("invalid projection install recovery journal")
    seen: set[str] = set()
    for index, item in enumerate(files):
        if not isinstance(item, dict) or set(item) != {"path", "existed", "backupPath"}:
            raise ProjectionInstallError("invalid projection install recovery journal")
        path = item.get("path")
        if not _is_managed_skill_path(path) or path in seen or not isinstance(item.get("existed"), bool):
            raise ProjectionInstallError("invalid projection install recovery journal")
        if item.get("backupPath") != f"{backup_directory}/file-{index}":
            raise ProjectionInstallError("invalid projection install recovery journal")
        seen.add(path)
    manifest = journal.get("manifest")
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"existed", "backupPath"}
        or not isinstance(manifest.get("existed"), bool)
        or manifest.get("backupPath") != f"{backup_directory}/install-manifest"
    ):
        raise ProjectionInstallError("invalid projection install recovery journal")
    return journal


def _cleanup_transaction(target: Path, journal: dict[str, Any]) -> None:
    journal = _validate_transaction_journal(journal)
    backup_directory = resolve_without_symlinks(
        target, journal["backupDirectory"], must_exist=False, label="transaction backup directory"
    )
    if backup_directory.exists():
        if not backup_directory.is_dir():
            raise ProjectionInstallError("transaction backup path is not a directory")
        shutil.rmtree(backup_directory)
    journal_path = _lexical_managed_path(target, INSTALL_TRANSACTION_PATH)
    if journal_path.exists():
        journal_path.unlink()
    backup_root = resolve_without_symlinks(
        target, INSTALL_BACKUP_ROOT, must_exist=False, label="transaction backup root"
    )
    if backup_root.is_dir() and not any(backup_root.iterdir()):
        backup_root.rmdir()


def _recover_install_transaction(target: Path) -> None:
    journal_path = _lexical_managed_path(target, INSTALL_TRANSACTION_PATH)
    if not journal_path.exists():
        return
    journal = _validate_transaction_journal(_load_json(journal_path))
    if journal["phase"] == "PREPARED":
        for item in journal["files"]:
            destination = _lexical_managed_path(target, item["path"], allow_leaf_symlink=True)
            if item["existed"]:
                backup = resolve_without_symlinks(
                    target, item["backupPath"], must_exist=True, label="transaction file backup"
                )
                if destination.exists() or destination.is_symlink():
                    if destination.is_dir() and not destination.is_symlink():
                        raise ProjectionInstallError("managed recovery destination became a directory")
                    destination.unlink()
                _write_atomic(destination, backup.read_bytes())
            elif destination.exists() or destination.is_symlink():
                if destination.is_dir() and not destination.is_symlink():
                    raise ProjectionInstallError("managed recovery destination became a directory")
                destination.unlink()
        manifest = journal["manifest"]
        manifest_path = _lexical_managed_path(target, INSTALL_MANIFEST_PATH, allow_leaf_symlink=True)
        if manifest["existed"]:
            backup = resolve_without_symlinks(
                target, manifest["backupPath"], must_exist=True, label="transaction manifest backup"
            )
            if manifest_path.exists() or manifest_path.is_symlink():
                manifest_path.unlink()
            _write_atomic(manifest_path, backup.read_bytes())
        elif manifest_path.exists() or manifest_path.is_symlink():
            manifest_path.unlink()
    _cleanup_transaction(target, journal)


def _begin_transaction(
    target: Path,
    operation: str,
    destinations: list[Path],
    manifest_path: Path,
) -> dict[str, Any]:
    token = uuid.uuid4().hex
    backup_relative = f"{INSTALL_BACKUP_ROOT}/{token}"
    backup_directory = resolve_without_symlinks(
        target, backup_relative, must_exist=False, label="transaction backup directory"
    )
    backup_directory.mkdir(parents=True)
    _fsync_directory(backup_directory)
    _fsync_directory(backup_directory.parent)
    files: list[dict[str, Any]] = []
    for index, destination in enumerate(destinations):
        relative = destination.relative_to(target).as_posix()
        existed = destination.is_file()
        backup_path = f"{backup_relative}/file-{index}"
        if existed:
            backup = resolve_without_symlinks(
                target, backup_path, must_exist=False, label="transaction file backup"
            )
            _write_atomic(backup, destination.read_bytes())
        files.append({"path": relative, "existed": existed, "backupPath": backup_path})
    manifest_existed = manifest_path.is_file()
    manifest_backup_path = f"{backup_relative}/install-manifest"
    if manifest_existed:
        backup = resolve_without_symlinks(
            target, manifest_backup_path, must_exist=False, label="transaction manifest backup"
        )
        _write_atomic(backup, manifest_path.read_bytes())
    journal = {
        "schemaVersion": "projection-install-transaction/v1",
        "operation": operation,
        "phase": "PREPARED",
        "backupDirectory": backup_relative,
        "files": files,
        "manifest": {"existed": manifest_existed, "backupPath": manifest_backup_path},
    }
    journal_path = _lexical_managed_path(target, INSTALL_TRANSACTION_PATH)
    _write_atomic(journal_path, deterministic_json_bytes(journal))
    return journal


def _commit_transaction(target: Path, journal: dict[str, Any]) -> None:
    journal["phase"] = "COMMITTED"
    journal_path = _lexical_managed_path(target, INSTALL_TRANSACTION_PATH)
    _write_atomic(journal_path, deterministic_json_bytes(journal))
    _cleanup_transaction(target, journal)


def _install_projection_unlocked(
    repository_root: Path,
    pack_root: Path,
    target_root: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    repository = Path(repository_root).resolve()
    target = Path(target_root).resolve()
    if not target.is_dir():
        raise ProjectionInstallError("install target must be an existing directory")
    transaction_path = _lexical_managed_path(target, INSTALL_TRANSACTION_PATH)
    if transaction_path.exists():
        if not apply:
            raise ProjectionInstallError("pending projection transaction recovery requires explicit --apply")
        _recover_install_transaction(target)
    projection, inputs = _projection_inputs(repository, pack_root, target)
    resolved = projection.pop("_validatedResolvedContext")
    integration_root_value = projection.pop("_validatedIntegrationRoot")
    if integration_root_value is not None:
        from .integration import check_integration_projection

        freshness = check_integration_projection(
            repository,
            Path(integration_root_value),
            target,
            runtime=projection["runtime"],
            intent=resolved["intent"],
            topic=resolved["topic"],
            requested_output=resolved["requestedOutput"],
            explicit_stage=resolved["stage"],
            reopen_signal=resolved.get("reopenSignal"),
        )
        if not freshness.fresh:
            raise ProjectionInstallError(
                "projection pack is stale for integration source: " + ", ".join(freshness.reasons)
            )
    install_manifest_path, current_manifest = _managed_manifest(repository, target)
    current_by_path = {
        item["path"]: item for item in (current_manifest or {}).get("installedFiles", [])
    }
    desired_paths = {item["path"] for item in inputs}
    if set(current_by_path) - desired_paths:
        raise ProjectionInstallError("managed skill set changed; uninstall before installing a different set")

    collisions: list[dict[str, str]] = []
    actions: list[dict[str, str]] = []
    for item in inputs:
        try:
            destination = resolve_without_symlinks(target, item["path"], label="skill install target")
        except PathBoundaryError as exc:
            raise ProjectionInstallError(str(exc)) from exc
        managed = current_by_path.get(item["path"])
        if destination.exists():
            if managed is None:
                collisions.append({"path": item["path"], "reason": "unmanaged-target-exists"})
                continue
            if not destination.is_file() or file_sha256(destination) != managed["installedSha256"]:
                collisions.append({"path": item["path"], "reason": "managed-target-drift"})
                continue
            operation = "UNCHANGED" if file_sha256(destination) == item["sourceSha256"] else "UPDATE"
        elif managed is not None:
            collisions.append({"path": item["path"], "reason": "managed-target-missing"})
            continue
        else:
            operation = "CREATE"
        actions.append(
            {
                "operation": operation,
                "source": item["sourcePath"],
                "target": item["path"],
                "sha256": item["sourceSha256"],
            }
        )

    result = {
        "schemaVersion": "projection-install-plan/v1",
        "mode": "APPLY" if apply else "DRY_RUN",
        "gate": "PASS" if not collisions else "NO_GO",
        "project": projection["project"],
        "runtime": projection["runtime"],
        "actions": actions,
        "collisions": collisions,
        "manifestPath": INSTALL_MANIFEST_PATH,
    }
    if not apply:
        return result
    if collisions:
        raise ProjectionInstallError("skill collision prevents projection install")

    persistent = _persistent_manifest(projection, inputs)
    SchemaStore(repository).validate("core/schemas/projection-install-manifest.schema.json", persistent)
    destinations = [
        resolve_without_symlinks(target, item["path"], label="skill install target")
        for item in inputs
    ]
    journal = _begin_transaction(target, "INSTALL", destinations, install_manifest_path)
    try:
        for item in inputs:
            destination = resolve_without_symlinks(target, item["path"], label="skill install target")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and file_sha256(destination) == item["sourceSha256"]:
                continue
            _write_atomic(destination, item["_source"].read_bytes())
        _write_atomic(install_manifest_path, deterministic_json_bytes(persistent))
        _commit_transaction(target, journal)
    except BaseException:
        _recover_install_transaction(target)
        raise
    return result


def install_projection(
    repository_root: Path,
    pack_root: Path,
    target_root: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    if not apply:
        return _install_projection_unlocked(repository_root, pack_root, target_root, apply=False)
    identity = process_lock_identity("projection-install", Path(target_root))
    try:
        with exclusive_process_lock(identity):
            return _install_projection_unlocked(repository_root, pack_root, target_root, apply=True)
    except ProcessLockError as exc:
        raise ProjectionInstallError(f"concurrent projection install rejected: {exc}") from exc


def _uninstall_projection_unlocked(
    repository_root: Path,
    target_root: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    repository = Path(repository_root).resolve()
    target = Path(target_root).resolve()
    if not target.is_dir():
        raise ProjectionInstallError("uninstall target must be an existing directory")
    transaction_path = _lexical_managed_path(target, INSTALL_TRANSACTION_PATH)
    if transaction_path.exists():
        if not apply:
            raise ProjectionInstallError("pending projection transaction recovery requires explicit --apply")
        _recover_install_transaction(target)
    manifest_path, manifest = _managed_manifest(repository, target)
    if manifest is None:
        result = {
            "schemaVersion": "projection-uninstall-plan/v1",
            "mode": "APPLY" if apply else "DRY_RUN",
            "gate": "NO_GO",
            "actions": [],
            "collisions": [{"path": INSTALL_MANIFEST_PATH, "reason": "install-manifest-missing"}],
        }
        if apply:
            raise ProjectionInstallError("projection install manifest is missing")
        return result

    collisions: list[dict[str, str]] = []
    actions: list[dict[str, str]] = []
    destinations: list[Path] = []
    for item in manifest["installedFiles"]:
        try:
            destination = resolve_without_symlinks(target, item["path"], label="managed skill path")
        except PathBoundaryError as exc:
            raise ProjectionInstallError(f"managed skill path contains symlink: {item['path']}") from exc
        destinations.append(destination)
        if not destination.is_file() or file_sha256(destination) != item["installedSha256"]:
            collisions.append({"path": item["path"], "reason": "managed-file-drift"})
        else:
            actions.append({"operation": "REMOVE", "target": item["path"], "sha256": item["installedSha256"]})
    result = {
        "schemaVersion": "projection-uninstall-plan/v1",
        "mode": "APPLY" if apply else "DRY_RUN",
        "gate": "PASS" if not collisions else "NO_GO",
        "actions": actions,
        "collisions": collisions,
    }
    if not apply:
        return result
    if collisions:
        raise ProjectionInstallError("managed file drift prevents projection uninstall")

    journal = _begin_transaction(target, "UNINSTALL", destinations, manifest_path)
    try:
        for destination in destinations:
            destination.unlink()
            _fsync_directory(destination.parent)
        manifest_path.unlink()
        _fsync_directory(manifest_path.parent)
        _commit_transaction(target, journal)
    except BaseException:
        _recover_install_transaction(target)
        raise
    for destination in destinations:
        parent = destination.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    return result


def uninstall_projection(
    repository_root: Path,
    target_root: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    if not apply:
        return _uninstall_projection_unlocked(repository_root, target_root, apply=False)
    identity = process_lock_identity("projection-install", Path(target_root))
    try:
        with exclusive_process_lock(identity):
            return _uninstall_projection_unlocked(repository_root, target_root, apply=True)
    except ProcessLockError as exc:
        raise ProjectionInstallError(f"concurrent projection uninstall rejected: {exc}") from exc
