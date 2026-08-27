from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from .anchored_fs import AnchoredPathError, AnchoredRoot
from .hashing import sha256_bytes
from .paths import PathBoundaryError, resolve_without_symlinks, safe_relative_path
from .projection import validate_projection_pack
from .process_lock import (
    ProcessLockError,
    exclusive_process_lock,
    exclusive_process_locks,
    process_lock_identity,
    recovery_attestation_phase,
)
from .schema import SchemaStore


INSTALL_MANIFEST_PATH = ".agent-evolution/projection-install-manifest.json"
INSTALL_TRANSACTION_PATH = ".agent-evolution/projection-install-transaction.json"


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
        resources = skill.get("resourceFiles") or [
            {
                "sourcePath": skill.get("sourceSkillPath", relative.as_posix()),
                "path": relative.as_posix(),
                "sha256": file_hashes.get(relative.as_posix()),
            }
        ]
        skill_root = PurePosixPath("skills", relative.parts[1])
        for resource in resources:
            resource_path = safe_relative_path(
                resource.get("path", ""), label="projected Skill resource path"
            )
            if resource_path.parts[:2] != skill_root.parts or len(resource_path.parts) < 3:
                raise ProjectionInstallError(
                    f"unsafe projected Skill resource path: {resource.get('path', '')}"
                )
            expected_hash = file_hashes.get(resource_path.as_posix())
            if expected_hash != resource.get("sha256"):
                raise ProjectionInstallError(
                    f"projected Skill resource manifest drift: {resource_path.as_posix()}"
                )
            try:
                with AnchoredRoot(pack) as pack_filesystem:
                    source_bytes = pack_filesystem.read_bytes(resource_path.as_posix())
            except AnchoredPathError as exc:
                raise ProjectionInstallError(
                    f"unsafe projected Skill resource path: {resource_path.as_posix()}"
                ) from exc
            if not expected_hash or sha256_bytes(source_bytes) != expected_hash:
                raise ProjectionInstallError(
                    f"projected Skill resource hash mismatch: {resource_path.as_posix()}"
                )
            target_path = PurePosixPath(
                ".agents", "skills", relative.parts[1], *resource_path.parts[2:]
            ).as_posix()
            inputs.append(
                {
                    "path": target_path,
                    "sourcePath": resource_path.as_posix(),
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


def _install_projection_unlocked(
    repository_root: Path,
    pack_root: Path,
    target_root: Path,
    *,
    source_root: Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    if apply:
        raise ProjectionInstallError(
            "automatic projection install is disabled; use the dry-run plan for project-authorized materialization"
        )
    repository = Path(repository_root).resolve()
    target_input = Path(target_root)
    if target_input.is_symlink():
        raise ProjectionInstallError("install target must not be a symlink")
    target = target_input.resolve()
    if not target.is_dir():
        raise ProjectionInstallError("install target must be an existing directory")
    source = Path(source_root).resolve() if source_root is not None else target
    try:
        with AnchoredRoot(target) as filesystem:
            recovery_identity = process_lock_identity("projection-install", target)
            pending_recovery = filesystem.exists(INSTALL_TRANSACTION_PATH) or recovery_attestation_phase(
                recovery_identity
            ) is not None
            if pending_recovery:
                raise ProjectionInstallError(
                    "pending projection transaction requires manual recovery; automatic recovery is disabled"
                )
            projection, inputs = _projection_inputs(repository, pack_root, source)
            resolved = projection.pop("_validatedResolvedContext")
            integration_root_value = projection.pop("_validatedIntegrationRoot")
            if integration_root_value is not None:
                from .integration import check_integration_projection

                freshness = check_integration_projection(
                    repository,
                    Path(integration_root_value),
                    source,
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
            _, current_manifest = _managed_manifest(repository, target, filesystem)
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
                    if sha256_bytes(current_bytes) != item["sourceSha256"]:
                        collisions.append({"path": item["path"], "reason": "managed-update-requires-review"})
                        continue
                    operation = "UNCHANGED"
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
            return result
    except AnchoredPathError as exc:
        raise ProjectionInstallError(f"anchored install path failed: {exc}") from exc


def install_projection(
    repository_root: Path,
    pack_root: Path,
    target_root: Path,
    *,
    source_root: Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    target_identity = process_lock_identity("projection-install", Path(target_root))
    pack_identity = process_lock_identity("projection-pack", Path(pack_root))
    try:
        with exclusive_process_locks([pack_identity, target_identity]):
            return _install_projection_unlocked(
                repository_root,
                pack_root,
                target_root,
                source_root=source_root,
                apply=apply,
            )
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
    if apply:
        raise ProjectionInstallError(
            "automatic projection uninstall is disabled; use the dry-run plan for project-authorized removal"
        )
    try:
        with AnchoredRoot(target) as filesystem:
            recovery_identity = process_lock_identity("projection-install", target)
            pending_recovery = filesystem.exists(INSTALL_TRANSACTION_PATH) or recovery_attestation_phase(
                recovery_identity
            ) is not None
            if pending_recovery:
                raise ProjectionInstallError(
                    "pending projection transaction requires manual recovery; automatic recovery is disabled"
                )
            _, manifest = _managed_manifest(repository, target, filesystem)
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
            for item in manifest["installedFiles"]:
                try:
                    resolve_without_symlinks(target, item["path"], label="managed skill path")
                    current_bytes = filesystem.read_bytes(item["path"]) if filesystem.is_file(item["path"]) else None
                except (PathBoundaryError, AnchoredPathError) as exc:
                    raise ProjectionInstallError(f"managed skill path contains symlink: {item['path']}") from exc
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
