from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .anchored_fs import AnchoredPathError, AnchoredRoot
from .capability_pack_registry import CapabilityVerificationSession
from .hashing import canonical_json_bytes, sha256_bytes
from .integration import load_integration
from .paths import PathBoundaryError, resolve_without_symlinks
from .project import load_capability_lock, verify_capability_lock
from .schema import SchemaStore, SchemaValidationError


HARNESS_ID = "agent-evolution-harness"
REGISTRATION_PATH = ".agent-evolution/registration.yaml"


class ProjectRegistrationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectRegistrationBootstrap:
    repository_root: Path
    source_root: Path
    registration_path: Path | None
    integration_root: Path
    control_plane_root: Path
    registration_witness: str
    integration_witness: str
    capability_lock_witness: str
    allowed_capability_ids: frozenset[str]


def _load_project_registration_structure(
    repository_root: Path,
    source_root: Path,
) -> tuple[ProjectRegistrationBootstrap, dict[str, Any]]:
    repository = Path(repository_root).resolve()
    source_input = Path(source_root)
    if source_input.is_symlink():
        raise ProjectRegistrationError("project source root must not be a symlink")
    source = source_input.resolve()
    if not source.is_dir():
        raise ProjectRegistrationError("project source root must be an existing directory")

    try:
        registration_path = resolve_without_symlinks(
            source,
            REGISTRATION_PATH,
            must_exist=True,
            label="registration path",
        )
        with AnchoredRoot(source) as filesystem:
            raw = filesystem.read_bytes(REGISTRATION_PATH)
    except (AnchoredPathError, FileNotFoundError, PathBoundaryError) as exc:
        raise ProjectRegistrationError(str(exc)) from exc
    try:
        registration = yaml.safe_load(raw.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ProjectRegistrationError("registration file is invalid YAML") from exc
    try:
        SchemaStore(repository).validate(
            "core/schemas/project-harness-registration.schema.json",
            registration,
        )
    except SchemaValidationError as exc:
        raise ProjectRegistrationError("registration schema is invalid: " + "; ".join(exc.errors)) from exc

    if registration["harnessId"] != HARNESS_ID:
        raise ProjectRegistrationError("harness identity mismatch")
    try:
        integration_root = resolve_without_symlinks(
            repository,
            registration["integrationPath"],
            must_exist=True,
            label="integration path",
        )
    except (FileNotFoundError, PathBoundaryError) as exc:
        raise ProjectRegistrationError(str(exc)) from exc
    if not integration_root.is_dir():
        raise ProjectRegistrationError("integration path must identify a directory")

    try:
        integration = load_integration(repository, integration_root)
    except Exception as exc:
        raise ProjectRegistrationError(f"registered integration is invalid: {exc}") from exc
    config = integration["config"]
    if config["id"] != registration["integrationId"]:
        raise ProjectRegistrationError("integration identity mismatch")
    if config["runtime"] != registration["runtime"]:
        raise ProjectRegistrationError("integration runtime mismatch")
    if config["sourceAccess"] != registration["sourceAccess"]:
        raise ProjectRegistrationError("integration source access mismatch")

    try:
        lock = load_capability_lock(repository, integration["controlPlaneRoot"])
    except Exception as exc:
        raise ProjectRegistrationError(f"registered capability lock is invalid: {exc}") from exc
    if lock["lockFingerprint"] != registration["capabilityLockFingerprint"]:
        raise ProjectRegistrationError("capability lock fingerprint mismatch")

    bootstrap = ProjectRegistrationBootstrap(
        repository_root=repository,
        source_root=source,
        registration_path=registration_path,
        integration_root=integration_root,
        control_plane_root=integration["controlPlaneRoot"],
        registration_witness="sha256:"
        + sha256_bytes(canonical_json_bytes(registration)),
        integration_witness="sha256:"
        + sha256_bytes(
            canonical_json_bytes(
                {
                    "config": integration["config"],
                    "authorityMap": integration["authorityMap"],
                    "integrationRoot": str(integration_root),
                    "controlPlaneRoot": str(integration["controlPlaneRoot"]),
                }
            )
        ),
        capability_lock_witness="sha256:"
        + sha256_bytes(canonical_json_bytes(lock)),
        allowed_capability_ids=frozenset(
            item["capabilityId"]
            for item in lock["capabilities"]
            if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK"
        ),
    )
    return bootstrap, {
        "registration": registration,
        "registrationPath": registration_path,
        "sourceRoot": source,
        "integrationRoot": integration_root,
        "integration": integration,
    }


def _bootstrap_registered_integration(
    repository_root: Path,
    source_root: Path,
    explicit_integration: Path | None,
) -> ProjectRegistrationBootstrap:
    bootstrap, _ = _load_project_registration_structure(repository_root, source_root)
    if (
        explicit_integration is not None
        and Path(explicit_integration).resolve() != bootstrap.integration_root
    ):
        raise ProjectRegistrationError(
            "explicit integration disagrees with project registration"
        )
    return bootstrap


def _require_unchanged_bootstrap(
    initial: ProjectRegistrationBootstrap,
    live: ProjectRegistrationBootstrap,
    verification_session: CapabilityVerificationSession,
) -> None:
    if initial == live:
        return
    error = ProjectRegistrationError(
        "project registration structural witness changed during verification"
    )
    verification_session._poison(error)
    raise error


def _load_project_registration_verified(
    repository_root: Path,
    source_root: Path,
    *,
    verification_session: CapabilityVerificationSession,
) -> dict[str, Any]:
    try:
        _, loaded = _load_project_registration_structure(repository_root, source_root)
        lock, _ = verify_capability_lock(
            Path(repository_root).resolve(),
            loaded["integration"]["controlPlaneRoot"],
            verification_session=verification_session,
        )
    except ProjectRegistrationError as exc:
        verification_session._poison(exc)
        raise
    except Exception as exc:
        error = ProjectRegistrationError(
            f"registered capability lock is invalid: {exc}"
        )
        verification_session._poison(error)
        raise error from exc
    if lock["lockFingerprint"] != loaded["registration"]["capabilityLockFingerprint"]:
        error = ProjectRegistrationError("capability lock fingerprint mismatch")
        verification_session._poison(error)
        raise error
    return loaded


def load_project_registration(
    repository_root: Path,
    source_root: Path,
    *,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:
    if verification_session is not None:
        return _load_project_registration_verified(
            repository_root,
            source_root,
            verification_session=verification_session,
        )
    bootstrap = _bootstrap_registered_integration(
        repository_root,
        source_root,
        None,
    )
    with CapabilityVerificationSession(
        bootstrap.repository_root,
        allowed_capability_ids=bootstrap.allowed_capability_ids,
    ) as private_session:
        loaded = _load_project_registration_verified(
            bootstrap.repository_root,
            bootstrap.source_root,
            verification_session=private_session,
        )
        live_bootstrap = _bootstrap_registered_integration(
            bootstrap.repository_root,
            bootstrap.source_root,
            None,
        )
        _require_unchanged_bootstrap(
            bootstrap,
            live_bootstrap,
            private_session,
        )
        return loaded


def check_project_registration(
    repository_root: Path,
    source_root: Path,
    *,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, str]:
    loaded = load_project_registration(
        repository_root,
        source_root,
        verification_session=verification_session,
    )
    registration = loaded["registration"]
    return {
        "schemaVersion": "project-registration-check/v1",
        "gate": "PASS",
        "harnessId": registration["harnessId"],
        "integrationId": registration["integrationId"],
        "integrationPath": registration["integrationPath"],
        "runtime": registration["runtime"],
        "sourceAccess": registration["sourceAccess"],
        "capabilityLockFingerprint": registration["capabilityLockFingerprint"],
    }


def _project_registration_present(source_root: Path) -> bool:
    source = Path(source_root).resolve()
    try:
        with AnchoredRoot(source) as filesystem:
            return filesystem.lstat(REGISTRATION_PATH) is not None
    except AnchoredPathError as exc:
        raise ProjectRegistrationError(f"registration path is unsafe: {exc}") from exc


def resolve_registered_integration(
    repository_root: Path,
    source_root: Path,
    explicit_integration: Path | None = None,
    *,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:
    repository = Path(repository_root).resolve()
    source = Path(source_root)
    if _project_registration_present(source):
        loaded = load_project_registration(
            repository,
            source,
            verification_session=verification_session,
        )
        if explicit_integration is not None and Path(explicit_integration).resolve() != loaded["integrationRoot"]:
            raise ProjectRegistrationError("explicit integration disagrees with project registration")
        return loaded
    if explicit_integration is None:
        raise ProjectRegistrationError(f"project registration is missing: {REGISTRATION_PATH}")
    integration_root = Path(explicit_integration).resolve()
    integration = load_integration(repository, integration_root)
    return {
        "registration": None,
        "registrationPath": None,
        "sourceRoot": source.resolve(),
        "integrationRoot": integration_root,
        "integration": integration,
    }


@contextmanager
def registered_integration_operation(
    repository_root: Path,
    source_root: Path,
    explicit_integration: Path | None = None,
) -> Iterator[tuple[dict[str, Any], CapabilityVerificationSession | None]]:
    repository = Path(repository_root).resolve()
    source = Path(source_root)
    if not _project_registration_present(source):
        yield (
            resolve_registered_integration(
                repository,
                source,
                explicit_integration,
            ),
            None,
        )
        return

    bootstrap = _bootstrap_registered_integration(
        repository,
        source,
        explicit_integration,
    )
    with CapabilityVerificationSession(
        bootstrap.repository_root,
        allowed_capability_ids=bootstrap.allowed_capability_ids,
    ) as verification_session:
        loaded = resolve_registered_integration(
            bootstrap.repository_root,
            bootstrap.source_root,
            explicit_integration,
            verification_session=verification_session,
        )
        live_bootstrap = _bootstrap_registered_integration(
            bootstrap.repository_root,
            bootstrap.source_root,
            explicit_integration,
        )
        _require_unchanged_bootstrap(
            bootstrap,
            live_bootstrap,
            verification_session,
        )
        yield loaded, verification_session
