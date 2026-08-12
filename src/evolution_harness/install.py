from __future__ import annotations

import json
import re
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from .anchored_fs import AnchoredPathError, AnchoredRoot
from .generated import deterministic_json_bytes
from .hashing import sha256_bytes
from .paths import PathBoundaryError, resolve_without_symlinks, safe_relative_path
from .projection import validate_projection_pack
from .process_lock import (
    ProcessLockError,
    exclusive_process_lock,
    exclusive_process_locks,
    process_lock_identity,
    recovery_attestation_phase,
    remove_recovery_attestation,
    verify_recovery_attestation,
    write_recovery_attestation,
)
from .schema import SchemaStore


INSTALL_MANIFEST_PATH = ".agent-evolution/projection-install-manifest.json"
INSTALL_TRANSACTION_PATH = ".agent-evolution/projection-install-transaction.json"
INSTALL_BACKUP_ROOT = ".agent-evolution/projection-install-backups"
_TRANSACTION_TOKEN = re.compile(r"^[0-9a-f]{32}$")


class ProjectionInstallError(RuntimeError):
    pass


def _managed_manifest(
    repository_root: Path,
    target_root: Path,
    filesystem: AnchoredRoot,
) -> tuple[Path, dict[str, Any] | None]:
    path = resolve_without_symlinks(target_root, INSTALL_MANIFEST_PATH, label="install manifest path")
    if not filesystem.exists(INSTALL_MANIFEST_PATH):
        return path, None
    try:
        manifest = json.loads(filesystem.read_bytes(INSTALL_MANIFEST_PATH))
    except (AnchoredPathError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectionInstallError("install manifest is unsafe or invalid") from exc
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
        expected_hash = file_hashes.get(relative.as_posix())
        try:
            with AnchoredRoot(pack) as pack_filesystem:
                source_bytes = pack_filesystem.read_bytes(relative.as_posix())
        except AnchoredPathError as exc:
            raise ProjectionInstallError(f"unsafe projected skill path: {raw_path}") from exc
        if not expected_hash or sha256_bytes(source_bytes) != expected_hash:
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
                "_sourceBytes": source_bytes,
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
            {key: value for key, value in item.items() if not key.startswith("_")}
            for item in sorted(inputs, key=lambda value: value["path"])
        ],
    }


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
    if journal.get("schemaVersion") != "projection-install-transaction/v2":
        raise ProjectionInstallError("invalid projection install recovery journal")
    if journal.get("operation") not in {"INSTALL", "UNINSTALL"}:
        raise ProjectionInstallError("invalid projection install recovery journal")
    if journal.get("phase") != "PREPARED":
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
        if not isinstance(item, dict) or set(item) != {
            "path",
            "existed",
            "backupPath",
            "backupSha256",
            "afterSha256",
        }:
            raise ProjectionInstallError("invalid projection install recovery journal")
        path = item.get("path")
        if not _is_managed_skill_path(path) or path in seen or not isinstance(item.get("existed"), bool):
            raise ProjectionInstallError("invalid projection install recovery journal")
        if item.get("backupPath") != f"{backup_directory}/file-{index}":
            raise ProjectionInstallError("invalid projection install recovery journal")
        backup_hash = item.get("backupSha256")
        if (item["existed"] and (not isinstance(backup_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", backup_hash))) or (
            not item["existed"] and backup_hash is not None
        ):
            raise ProjectionInstallError("invalid projection install recovery journal")
        after_hash = item.get("afterSha256")
        if after_hash is not None and (not isinstance(after_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", after_hash)):
            raise ProjectionInstallError("invalid projection install recovery journal")
        seen.add(path)
    manifest = journal.get("manifest")
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"existed", "backupPath", "backupSha256", "afterSha256"}
        or not isinstance(manifest.get("existed"), bool)
        or manifest.get("backupPath") != f"{backup_directory}/install-manifest"
    ):
        raise ProjectionInstallError("invalid projection install recovery journal")
    manifest_hash = manifest.get("backupSha256")
    if (
        manifest["existed"]
        and (not isinstance(manifest_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest_hash))
    ) or (not manifest["existed"] and manifest_hash is not None):
        raise ProjectionInstallError("invalid projection install recovery journal")
    manifest_after_hash = manifest.get("afterSha256")
    if manifest_after_hash is not None and (
        not isinstance(manifest_after_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest_after_hash)
    ):
        raise ProjectionInstallError("invalid projection install recovery journal")
    return journal


def _cleanup_transaction(
    target: Path,
    filesystem: AnchoredRoot,
    journal: dict[str, Any],
    *,
    identity: str,
) -> None:
    journal = _validate_transaction_journal(journal)
    backup_directory = journal["backupDirectory"]
    if filesystem.exists(backup_directory):
        if not filesystem.is_dir(backup_directory):
            raise ProjectionInstallError("transaction backup path is not a directory")
        filesystem.remove_tree(backup_directory)
    filesystem.unlink(INSTALL_TRANSACTION_PATH, missing_ok=True)
    filesystem.rmdir_if_empty(INSTALL_BACKUP_ROOT)
    remove_recovery_attestation(identity, missing_ok=True)


def _recover_install_transaction_anchored(target: Path, filesystem: AnchoredRoot) -> None:
    identity = process_lock_identity("projection-install", target)
    if not filesystem.exists(INSTALL_TRANSACTION_PATH):
        try:
            orphan_phase = recovery_attestation_phase(identity)
            if orphan_phase == "PREPARED":
                raise ProjectionInstallError("trusted PREPARED recovery attestation has no journal")
            remove_recovery_attestation(identity, missing_ok=True)
        except ProcessLockError as exc:
            raise ProjectionInstallError(str(exc)) from exc
        return
    try:
        journal_bytes = filesystem.read_bytes(INSTALL_TRANSACTION_PATH)
        recovery_phase = verify_recovery_attestation(identity, journal_bytes)
    except (AnchoredPathError, ProcessLockError) as exc:
        raise ProjectionInstallError(f"trusted recovery attestation failed: {exc}") from exc
    try:
        journal = _validate_transaction_journal(json.loads(journal_bytes))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectionInstallError("invalid projection install recovery journal") from exc

    if recovery_phase == "PREPARED":
        for item in journal["files"]:
            if item["existed"]:
                try:
                    data = filesystem.read_bytes(item["backupPath"])
                except AnchoredPathError as exc:
                    raise ProjectionInstallError("trusted recovery backup is missing or unsafe") from exc
                if sha256_bytes(data) != item["backupSha256"]:
                    raise ProjectionInstallError("trusted recovery backup hash mismatch")
            if filesystem.exists(item["path"]):
                if not filesystem.is_file(item["path"]):
                    raise ProjectionInstallError("managed recovery destination became a directory")
                current_hash = sha256_bytes(filesystem.read_bytes(item["path"]))
            else:
                current_hash = None
            before_hash = item["backupSha256"] if item["existed"] else None
            if current_hash != before_hash:
                raise ProjectionInstallError(
                    "partial projection transaction requires manual recovery; target paths were preserved"
                )
        manifest = journal["manifest"]
        if manifest["existed"]:
            try:
                data = filesystem.read_bytes(manifest["backupPath"])
            except AnchoredPathError as exc:
                raise ProjectionInstallError("trusted recovery manifest backup is missing or unsafe") from exc
            if sha256_bytes(data) != manifest["backupSha256"]:
                raise ProjectionInstallError("trusted recovery manifest backup hash mismatch")

        if filesystem.exists(INSTALL_MANIFEST_PATH):
            if not filesystem.is_file(INSTALL_MANIFEST_PATH):
                raise ProjectionInstallError("recovery manifest destination became a directory")
            current_manifest_hash = sha256_bytes(filesystem.read_bytes(INSTALL_MANIFEST_PATH))
        else:
            current_manifest_hash = None
        manifest_before_hash = manifest["backupSha256"] if manifest["existed"] else None
        if current_manifest_hash != manifest_before_hash:
            raise ProjectionInstallError(
                "partial projection transaction requires manual recovery; target paths were preserved"
            )
        try:
            write_recovery_attestation(identity, journal_bytes, phase="COMMITTED")
        except ProcessLockError as exc:
            raise ProjectionInstallError(str(exc)) from exc
    _cleanup_transaction(target, filesystem, journal, identity=identity)


def _recover_install_transaction(target: Path) -> None:
    try:
        with AnchoredRoot(target) as filesystem:
            _recover_install_transaction_anchored(target, filesystem)
    except AnchoredPathError as exc:
        raise ProjectionInstallError(str(exc)) from exc


def _begin_transaction(
    target: Path,
    operation: str,
    destinations: list[Path],
    manifest_path: Path,
    filesystem: AnchoredRoot | None = None,
    *,
    after_sha256_by_path: dict[str, str | None],
    manifest_after_sha256: str | None,
) -> dict[str, Any]:
    if filesystem is None:
        try:
            with AnchoredRoot(target) as anchored:
                return _begin_transaction(
                    target,
                    operation,
                    destinations,
                    manifest_path,
                    anchored,
                    after_sha256_by_path=after_sha256_by_path,
                    manifest_after_sha256=manifest_after_sha256,
                )
        except AnchoredPathError as exc:
            raise ProjectionInstallError(str(exc)) from exc
    relative_destinations = [destination.relative_to(target).as_posix() for destination in destinations]
    if len(set(relative_destinations)) != len(relative_destinations) or set(after_sha256_by_path) != set(
        relative_destinations
    ):
        raise ProjectionInstallError("transaction after-image set does not match destinations")
    for after_hash in [*after_sha256_by_path.values(), manifest_after_sha256]:
        if after_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", after_hash):
            raise ProjectionInstallError("transaction after-image hash is invalid")
    token = uuid.uuid4().hex
    backup_relative = f"{INSTALL_BACKUP_ROOT}/{token}"
    try:
        filesystem.mkdir_new(backup_relative)
    except AnchoredPathError as exc:
        raise ProjectionInstallError("cannot create anchored transaction backup") from exc
    files: list[dict[str, Any]] = []
    for index, destination in enumerate(destinations):
        relative = destination.relative_to(target).as_posix()
        existed = filesystem.is_file(relative)
        backup_path = f"{backup_relative}/file-{index}"
        backup_hash = None
        if existed:
            data = filesystem.read_bytes(relative)
            filesystem.write_bytes(backup_path, data)
            backup_hash = sha256_bytes(data)
        files.append(
            {
                "path": relative,
                "existed": existed,
                "backupPath": backup_path,
                "backupSha256": backup_hash,
                "afterSha256": after_sha256_by_path[relative],
            }
        )
    manifest_relative = manifest_path.relative_to(target).as_posix()
    manifest_existed = filesystem.is_file(manifest_relative)
    manifest_backup_path = f"{backup_relative}/install-manifest"
    manifest_backup_hash = None
    if manifest_existed:
        data = filesystem.read_bytes(manifest_relative)
        filesystem.write_bytes(manifest_backup_path, data)
        manifest_backup_hash = sha256_bytes(data)
    journal = {
        "schemaVersion": "projection-install-transaction/v2",
        "operation": operation,
        "phase": "PREPARED",
        "backupDirectory": backup_relative,
        "files": files,
        "manifest": {
            "existed": manifest_existed,
            "backupPath": manifest_backup_path,
            "backupSha256": manifest_backup_hash,
            "afterSha256": manifest_after_sha256,
        },
    }
    journal_bytes = deterministic_json_bytes(journal)
    filesystem.write_bytes(INSTALL_TRANSACTION_PATH, journal_bytes)
    identity = process_lock_identity("projection-install", target)
    try:
        write_recovery_attestation(identity, journal_bytes, phase="PREPARED")
    except ProcessLockError as exc:
        raise ProjectionInstallError(str(exc)) from exc
    return journal


def _commit_transaction(target: Path, filesystem: AnchoredRoot, journal: dict[str, Any]) -> None:
    journal_bytes = deterministic_json_bytes(journal)
    identity = process_lock_identity("projection-install", target)
    try:
        write_recovery_attestation(identity, journal_bytes, phase="COMMITTED")
    except ProcessLockError as exc:
        raise ProjectionInstallError(str(exc)) from exc
    _cleanup_transaction(target, filesystem, journal, identity=identity)


def _install_projection_unlocked(
    repository_root: Path,
    pack_root: Path,
    target_root: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    repository = Path(repository_root).resolve()
    target_input = Path(target_root)
    if target_input.is_symlink():
        raise ProjectionInstallError("install target must not be a symlink")
    target = target_input.resolve()
    if not target.is_dir():
        raise ProjectionInstallError("install target must be an existing directory")
    try:
        with AnchoredRoot(target) as filesystem:
            recovery_identity = process_lock_identity("projection-install", target)
            pending_recovery = filesystem.exists(INSTALL_TRANSACTION_PATH) or recovery_attestation_phase(
                recovery_identity
            ) is not None
            if pending_recovery:
                if not apply:
                    raise ProjectionInstallError("pending projection transaction recovery requires explicit --apply")
                _recover_install_transaction_anchored(target, filesystem)
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
            install_manifest_path, current_manifest = _managed_manifest(repository, target, filesystem)
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
                    resolve_without_symlinks(target, item["path"], label="skill install target")
                    present = filesystem.exists(item["path"])
                    current_bytes = filesystem.read_bytes(item["path"]) if filesystem.is_file(item["path"]) else None
                except (PathBoundaryError, AnchoredPathError) as exc:
                    raise ProjectionInstallError(f"skill install target contains a symlink or unsafe path: {item['path']}") from exc
                managed = current_by_path.get(item["path"])
                if present:
                    if managed is None:
                        collisions.append({"path": item["path"], "reason": "unmanaged-target-exists"})
                        continue
                    if current_bytes is None or sha256_bytes(current_bytes) != managed["installedSha256"]:
                        collisions.append({"path": item["path"], "reason": "managed-target-drift"})
                        continue
                    operation = "UNCHANGED" if sha256_bytes(current_bytes) == item["sourceSha256"] else "UPDATE"
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
            persistent_bytes = deterministic_json_bytes(persistent)
            destinations = [
                resolve_without_symlinks(target, item["path"], label="skill install target")
                for item in inputs
            ]
            journal = _begin_transaction(
                target,
                "INSTALL",
                destinations,
                install_manifest_path,
                filesystem,
                after_sha256_by_path={item["path"]: item["sourceSha256"] for item in inputs},
                manifest_after_sha256=sha256_bytes(persistent_bytes),
            )
            try:
                for item in inputs:
                    resolve_without_symlinks(target, item["path"], label="skill install target")
                    if filesystem.is_file(item["path"]):
                        current_bytes = filesystem.read_bytes(item["path"])
                        if sha256_bytes(current_bytes) == item["sourceSha256"]:
                            continue
                    filesystem.write_bytes(item["path"], item["_sourceBytes"])
                filesystem.write_bytes(INSTALL_MANIFEST_PATH, persistent_bytes)
                _commit_transaction(target, filesystem, journal)
            except BaseException:
                _recover_install_transaction_anchored(target, filesystem)
                raise
            return result
    except AnchoredPathError as exc:
        raise ProjectionInstallError(f"anchored install path failed: {exc}") from exc


def install_projection(
    repository_root: Path,
    pack_root: Path,
    target_root: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    target_identity = process_lock_identity("projection-install", Path(target_root))
    pack_identity = process_lock_identity("projection-pack", Path(pack_root))
    try:
        with exclusive_process_locks([pack_identity, target_identity]):
            return _install_projection_unlocked(repository_root, pack_root, target_root, apply=apply)
    except ProcessLockError as exc:
        raise ProjectionInstallError(f"concurrent projection install or projection pack access rejected: {exc}") from exc


def _uninstall_projection_unlocked(
    repository_root: Path,
    target_root: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    repository = Path(repository_root).resolve()
    target_input = Path(target_root)
    if target_input.is_symlink():
        raise ProjectionInstallError("uninstall target must not be a symlink")
    target = target_input.resolve()
    if not target.is_dir():
        raise ProjectionInstallError("uninstall target must be an existing directory")
    try:
        with AnchoredRoot(target) as filesystem:
            recovery_identity = process_lock_identity("projection-install", target)
            pending_recovery = filesystem.exists(INSTALL_TRANSACTION_PATH) or recovery_attestation_phase(
                recovery_identity
            ) is not None
            if pending_recovery:
                if not apply:
                    raise ProjectionInstallError("pending projection transaction recovery requires explicit --apply")
                _recover_install_transaction_anchored(target, filesystem)
            manifest_path, manifest = _managed_manifest(repository, target, filesystem)
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
                    current_bytes = filesystem.read_bytes(item["path"]) if filesystem.is_file(item["path"]) else None
                except (PathBoundaryError, AnchoredPathError) as exc:
                    raise ProjectionInstallError(f"managed skill path contains symlink: {item['path']}") from exc
                destinations.append(destination)
                if current_bytes is None or sha256_bytes(current_bytes) != item["installedSha256"]:
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

            journal = _begin_transaction(
                target,
                "UNINSTALL",
                destinations,
                manifest_path,
                filesystem,
                after_sha256_by_path={item["path"]: None for item in manifest["installedFiles"]},
                manifest_after_sha256=None,
            )
            try:
                for item in manifest["installedFiles"]:
                    filesystem.unlink(item["path"])
                filesystem.unlink(INSTALL_MANIFEST_PATH)
                _commit_transaction(target, filesystem, journal)
            except BaseException:
                _recover_install_transaction_anchored(target, filesystem)
                raise
            for item in manifest["installedFiles"]:
                filesystem.rmdir_if_empty(PurePosixPath(item["path"]).parent.as_posix())
            return result
    except AnchoredPathError as exc:
        raise ProjectionInstallError(f"anchored uninstall path failed: {exc}") from exc


def uninstall_projection(
    repository_root: Path,
    target_root: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    identity = process_lock_identity("projection-install", Path(target_root))
    try:
        with exclusive_process_lock(identity):
            return _uninstall_projection_unlocked(repository_root, target_root, apply=apply)
    except ProcessLockError as exc:
        raise ProjectionInstallError(f"concurrent projection uninstall rejected: {exc}") from exc
