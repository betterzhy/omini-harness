from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .anchored_fs import AnchoredPathError, AnchoredRoot
from .integration import load_integration
from .paths import PathBoundaryError, resolve_without_symlinks
from .project import verify_capability_lock
from .schema import SchemaStore, SchemaValidationError


HARNESS_ID = "agent-evolution-harness"
REGISTRATION_PATH = ".agent-evolution/registration.yaml"


class ProjectRegistrationError(ValueError):
    pass


def load_project_registration(repository_root: Path, source_root: Path) -> dict[str, Any]:
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
        lock, _ = verify_capability_lock(repository, integration["controlPlaneRoot"])
    except Exception as exc:
        raise ProjectRegistrationError(f"registered capability lock is invalid: {exc}") from exc
    if lock["lockFingerprint"] != registration["capabilityLockFingerprint"]:
        raise ProjectRegistrationError("capability lock fingerprint mismatch")

    return {
        "registration": registration,
        "registrationPath": registration_path,
        "sourceRoot": source,
        "integrationRoot": integration_root,
        "integration": integration,
    }


def check_project_registration(repository_root: Path, source_root: Path) -> dict[str, str]:
    loaded = load_project_registration(repository_root, source_root)
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
) -> dict[str, Any]:
    repository = Path(repository_root).resolve()
    source = Path(source_root)
    if _project_registration_present(source):
        loaded = load_project_registration(repository, source)
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
