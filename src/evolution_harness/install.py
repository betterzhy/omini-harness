from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from .generated import deterministic_json_bytes
from .hashing import file_sha256, sha256_bytes
from .paths import PathBoundaryError, resolve_within, safe_relative_path
from .schema import SchemaStore


INSTALL_MANIFEST_PATH = ".agent-evolution/projection-install-manifest.json"


class ProjectionInstallError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _managed_manifest(repository_root: Path, target_root: Path) -> tuple[Path, dict[str, Any] | None]:
    path = resolve_within(target_root, INSTALL_MANIFEST_PATH, label="install manifest path")
    if not path.exists():
        return path, None
    manifest = _load_json(path)
    SchemaStore(repository_root).validate("core/schemas/projection-install-manifest.schema.json", manifest)
    return path, manifest


def _projection_inputs(pack_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pack = Path(pack_root).resolve()
    manifest_path = pack / "projection-manifest.json"
    if not manifest_path.is_file():
        raise ProjectionInstallError("projection manifest is missing")
    manifest = _load_json(manifest_path)
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
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def install_projection(
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
    projection, inputs = _projection_inputs(pack_root)
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
            destination = resolve_within(target, item["path"], label="skill install target")
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
    backups: list[tuple[Path, Path]] = []
    created: list[Path] = []
    try:
        for item in inputs:
            destination = resolve_within(target, item["path"], label="skill install target")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and file_sha256(destination) == item["sourceSha256"]:
                continue
            if destination.exists():
                backup = destination.parent / f".{destination.name}.backup-{uuid.uuid4().hex}"
                os.replace(destination, backup)
                backups.append((destination, backup))
            else:
                created.append(destination)
            _write_atomic(destination, item["_source"].read_bytes())
        _write_atomic(install_manifest_path, deterministic_json_bytes(persistent))
    except Exception:
        for destination in reversed(created):
            if destination.exists():
                destination.unlink()
        for destination, backup in reversed(backups):
            if destination.exists():
                destination.unlink()
            if backup.exists():
                os.replace(backup, destination)
        raise
    for _, backup in backups:
        if backup.exists():
            backup.unlink()
    return result


def uninstall_projection(
    repository_root: Path,
    target_root: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    repository = Path(repository_root).resolve()
    target = Path(target_root).resolve()
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
            destination = resolve_within(target, item["path"], label="managed skill path")
        except PathBoundaryError as exc:
            raise ProjectionInstallError(str(exc)) from exc
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

    backups: list[tuple[Path, Path]] = []
    manifest_backup = manifest_path.parent / f".{manifest_path.name}.backup-{uuid.uuid4().hex}"
    try:
        for destination in destinations:
            backup = destination.parent / f".{destination.name}.backup-{uuid.uuid4().hex}"
            os.replace(destination, backup)
            backups.append((destination, backup))
        os.replace(manifest_path, manifest_backup)
    except Exception:
        for destination, backup in reversed(backups):
            if backup.exists():
                os.replace(backup, destination)
        if manifest_backup.exists():
            os.replace(manifest_backup, manifest_path)
        raise
    for _, backup in backups:
        backup.unlink()
    manifest_backup.unlink()
    for destination in destinations:
        parent = destination.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    return result
