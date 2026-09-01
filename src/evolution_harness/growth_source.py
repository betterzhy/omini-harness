from __future__ import annotations

import copy
import os
import re
import subprocess
from pathlib import Path
from typing import Any, NoReturn

from .authority import build_authority_snapshot
from .growth_assessment import GrowthAssessmentError
from .paths import PathBoundaryError, safe_relative_path
from .registration import ProjectRegistrationError, load_project_registration


_GIT_PATH = "/usr/bin/git"
_GIT_OBJECT_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_GIT_ENVIRONMENT = {
    "PATH": "/usr/bin:/bin",
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


def _fail(
    code: str,
    message: str,
    *,
    cause: BaseException | None = None,
) -> NoReturn:
    error = GrowthAssessmentError(code, message)
    if cause is None:
        raise error
    raise error from cause


def _canonical_source_root(source_root: Path, *, code: str) -> Path:
    source = Path(source_root)
    if not source.is_absolute() or source.is_symlink():
        _fail(code, "source root must be an absolute non-symlink directory")
    try:
        resolved = source.resolve(strict=True)
    except OSError as exc:
        _fail(code, "source root is unavailable", cause=exc)
    if resolved != source or not resolved.is_dir():
        _fail(code, "source root must be a canonical non-symlink directory")
    return resolved


def _exact_safe_posix(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        _fail("SOURCE_AUTHORITY_NO_GO", f"{label} must be a safe relative path")
    try:
        normalized = safe_relative_path(value, label=label).as_posix()
    except PathBoundaryError as exc:
        _fail(
            "SOURCE_AUTHORITY_NO_GO",
            f"{label} must be a safe relative path",
            cause=exc,
        )
    if normalized != value:
        _fail("SOURCE_AUTHORITY_NO_GO", f"{label} must use its exact safe POSIX spelling")
    return normalized


def _validate_replayable_evidence(
    request: dict[str, Any], snapshot: dict[str, Any]
) -> None:
    live_records: list[tuple[str, dict[str, Any]]] = []
    for record in snapshot["authorities"]:
        live_records.append(
            (
                _exact_safe_posix(record.get("path"), label="live authority path"),
                record,
            )
        )

    evidence_items = request.get("evidence")
    if not isinstance(evidence_items, list):
        _fail("SOURCE_AUTHORITY_NO_GO", "request evidence must be a list")
    for evidence in evidence_items:
        if not isinstance(evidence, dict):
            _fail("SOURCE_AUTHORITY_NO_GO", "request evidence item is invalid")
        if evidence.get("availability") != "REPLAYABLE":
            continue
        reference = _exact_safe_posix(
            evidence.get("reference"), label="replayable evidence reference"
        )
        matches = [
            record
            for live_path, record in live_records
            if live_path == reference and record.get("role") != "DERIVED"
        ]
        if len(matches) != 1:
            _fail(
                "SOURCE_AUTHORITY_NO_GO",
                "replayable evidence must match exactly one non-derived live authority",
            )
        record = matches[0]
        if evidence.get("digest") != "sha256:" + record["sha256"]:
            _fail(
                "SOURCE_AUTHORITY_NO_GO",
                "replayable evidence digest does not match live authority bytes",
            )
        if evidence.get("revision") != snapshot["sourceRevision"]["head"]:
            _fail(
                "SOURCE_AUTHORITY_NO_GO",
                "replayable evidence revision does not match live source revision",
            )


def _validate_registered_source(
    repository_root: Path,
    source_root: Path,
    request: dict[str, Any],
) -> dict[str, Any]:
    source = _canonical_source_root(
        source_root,
        code="SOURCE_REGISTRATION_INVALID",
    )
    try:
        loaded = load_project_registration(repository_root, source)
    except ProjectRegistrationError as exc:
        _fail(
            "SOURCE_REGISTRATION_INVALID",
            "registered source registration or exact lock is invalid",
            cause=exc,
        )

    registration = loaded["registration"]
    config = loaded["integration"]["config"]
    requested_source = request["source"]
    expected_context = {
        "projectId": config["projectId"],
        "integrationId": registration["integrationId"],
        "runtime": registration["runtime"],
    }
    if any(requested_source.get(key) != value for key, value in expected_context.items()):
        _fail(
            "SOURCE_CONTEXT_MISMATCH",
            "request source context does not match registered integration",
        )
    if (
        requested_source.get("capabilityLockFingerprint")
        != registration["capabilityLockFingerprint"]
    ):
        _fail(
            "SOURCE_LOCK_MISMATCH",
            "request capability lock does not match registered exact lock",
        )

    try:
        snapshot = build_authority_snapshot(
            repository_root,
            loaded["integrationRoot"],
            source,
        )
    except Exception as exc:
        _fail(
            "SOURCE_AUTHORITY_NO_GO",
            "registered source Authority Snapshot is invalid",
            cause=exc,
        )
    live_revision = snapshot["sourceRevision"]
    if snapshot["gate"] != "PASS" or live_revision.get("authoritySetStatus") != (
        "CLEAN_FOR_AUTHORITY_SET"
    ):
        _fail(
            "SOURCE_AUTHORITY_NO_GO",
            "registered source Authority Snapshot is not clean and passing",
        )
    requested_revision = requested_source.get("sourceRevision")
    expected_revision = {
        key: live_revision.get(key) for key in ("kind", "head", "tree")
    }
    if (
        live_revision.get("kind") != "GIT"
        or not isinstance(requested_revision, dict)
        or requested_revision != expected_revision
    ):
        _fail(
            "SOURCE_REVISION_MISMATCH",
            "request source revision does not match live Git identity",
        )
    if requested_source.get("authoritySnapshotFingerprint") != snapshot[
        "snapshotFingerprint"
    ]:
        _fail(
            "SOURCE_AUTHORITY_NO_GO",
            "request Authority Snapshot fingerprint does not match live authority",
        )

    _validate_replayable_evidence(request, snapshot)
    return copy.deepcopy(requested_source)


def _git_rev_parse(repository_root: Path, expression: str) -> str:
    try:
        completed = subprocess.run(
            [_GIT_PATH, "rev-parse", expression],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            env=dict(_GIT_ENVIRONMENT),
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _fail(
            "SOURCE_SELF_INVALID",
            "Harness-self Git identity is unavailable",
            cause=exc,
        )
    value = completed.stdout.strip()
    if _GIT_OBJECT_PATTERN.fullmatch(value) is None:
        _fail("SOURCE_SELF_INVALID", "Harness-self Git identity is invalid")
    return value


def _physical_identity(path: Path) -> tuple[int, int]:
    try:
        current = path.stat()
    except OSError as exc:
        _fail("SOURCE_SELF_INVALID", "Harness-self root is unavailable", cause=exc)
    return current.st_dev, current.st_ino


def _validate_harness_self(
    repository_root: Path,
    source_root: Path,
    request: dict[str, Any],
) -> dict[str, Any]:
    source = _canonical_source_root(source_root, code="SOURCE_SELF_INVALID")
    repository_input = Path(repository_root)
    try:
        repository = repository_input.resolve(strict=True)
    except OSError as exc:
        _fail(
            "SOURCE_SELF_INVALID",
            "Harness repository root is unavailable",
            cause=exc,
        )
    if not repository.is_dir():
        _fail("SOURCE_SELF_INVALID", "Harness repository root is not a directory")
    try:
        same_root = os.path.samefile(repository, source)
    except OSError as exc:
        _fail(
            "SOURCE_SELF_INVALID",
            "Harness-self physical root is unavailable",
            cause=exc,
        )
    if not same_root:
        _fail(
            "SOURCE_SELF_INVALID",
            "HARNESS_SELF requires the source and Harness repository to be the same physical root",
        )

    requested_source = request["source"]
    if (
        requested_source.get("projectId") != "agent-evolution-harness"
        or requested_source.get("runtime") not in {"CHATGPT", "CODEX"}
        or any(
            field in requested_source
            for field in (
                "integrationId",
                "authoritySnapshotFingerprint",
                "capabilityLockFingerprint",
            )
        )
    ):
        _fail("SOURCE_SELF_INVALID", "Harness-self source context is invalid")
    task = request.get("task")
    if not isinstance(task, dict):
        _fail("SOURCE_SELF_INVALID", "Harness-self task identity is invalid")
    fixed_presence = [field in task for field in ("candidate", "parent", "tree")]
    if any(fixed_presence) and not all(fixed_presence):
        _fail("SOURCE_SELF_INVALID", "fixed Candidate identity must be complete")
    evidence = request.get("evidence")
    if not isinstance(evidence, list) or any(
        not isinstance(item, dict) or item.get("availability") == "REPLAYABLE"
        for item in evidence
    ):
        _fail(
            "SOURCE_SELF_INVALID",
            "HARNESS_SELF does not support REPLAYABLE evidence in Phase 1",
        )

    initial_identity = _physical_identity(repository)
    head = _git_rev_parse(repository, "HEAD")
    tree = _git_rev_parse(repository, "HEAD^{tree}")
    if _physical_identity(repository) != initial_identity:
        _fail(
            "SOURCE_SELF_INVALID",
            "Harness-self physical root changed during validation",
        )
    requested_revision = requested_source.get("sourceRevision")
    if requested_revision != {"kind": "GIT", "head": head, "tree": tree}:
        _fail(
            "SOURCE_SELF_INVALID",
            "Harness-self request revision does not match live Git identity",
        )
    return copy.deepcopy(requested_source)


def validate_growth_source(
    repository_root: Path,
    source_root: Path,
    request: dict[str, Any],
) -> dict[str, Any]:
    """Validate one normalized GAP source context without writing either repository."""
    if not isinstance(request, dict) or not isinstance(request.get("source"), dict):
        _fail("SOURCE_CONTEXT_MISMATCH", "request source context is invalid")
    source_kind = request["source"].get("sourceKind")
    if source_kind == "REGISTERED_PROJECT":
        return _validate_registered_source(repository_root, source_root, request)
    if source_kind == "HARNESS_SELF":
        return _validate_harness_self(repository_root, source_root, request)
    _fail("SOURCE_CONTEXT_MISMATCH", "request source kind is unsupported")
