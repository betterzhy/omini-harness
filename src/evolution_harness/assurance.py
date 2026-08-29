from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import json
import yaml

from .capability_pack_registry import (
    CapabilityVerificationSession,
    build_capability_pack_registry,
    load_capability_pack_registrations,
)
from .catalog import build_all_catalogs
from .generated import deterministic_json_bytes
from .integration import load_integration
from .learning import _candidate_paths, _experience_paths, _load_yaml
from .project import build_capability_lock, load_project_binding, load_project_state
from .projection import check_projection_freshness
from .registry import (
    build_design_learning_registry,
    build_design_registry,
    build_engineering_registry,
)
from .schema import SchemaStore
from .validation import validate_repository


def _issue(code: str, message: str, path: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "message": message}
    if path:
        value["path"] = path
    return value


def _check_json_file(path: Path, expected: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    expected_bytes = deterministic_json_bytes(expected)
    if not path.exists():
        issues.append(_issue("GENERATED_MISSING", f"generated artifact missing: {path}", str(path)))
        return
    if path.read_bytes() != expected_bytes:
        issues.append(_issue("GENERATED_DRIFT", f"generated artifact drift: {path}", str(path)))


def _validate_learning(root: Path, issues: list[dict[str, Any]]) -> None:
    store = SchemaStore(root)
    experience_ids: set[str] = set()
    for path in _experience_paths(root):
        try:
            value = _load_yaml(path)
            store.validate("design/schemas/experience.schema.json", value)
            experience_ids.add(value["experienceId"])
        except Exception as exc:
            issues.append(_issue("EXPERIENCE_INVALID", str(exc), str(path)))
    eval_ids: set[str] = set()
    for path in sorted((root / "design/evals").glob("*.yaml")):
        try:
            value = _load_yaml(path)
            store.validate("design/schemas/eval.schema.json", value)
            eval_ids.add(value["evalId"])
        except Exception as exc:
            issues.append(_issue("EVAL_INVALID", str(exc), str(path)))
    for path in _candidate_paths(root):
        try:
            wrapper = _load_yaml(path)
            store.validate("design/schemas/candidate.schema.json", wrapper)
            missing = [value for value in wrapper["sourceExperiences"] if value not in experience_ids]
            if missing:
                issues.append(_issue("CANDIDATE_SOURCE_MISSING", f"candidate source experiences missing: {missing}", str(path)))
            missing_evals = [value for value in wrapper.get("evalRequirements", []) if value not in eval_ids]
            if missing_evals:
                issues.append(_issue("CANDIDATE_EVAL_MISSING", f"candidate eval requirements missing: {missing_evals}", str(path)))
            proposed = _load_yaml(path.parent / "proposed/asset.yaml")
            kind = proposed.get("id", "").split(":", 1)[0]
            store.validate(f"design/schemas/{kind}.schema.json", proposed)
        except Exception as exc:
            issues.append(_issue("CANDIDATE_INVALID", str(exc), str(path)))


def _validate_engineering(root: Path, issues: list[dict[str, Any]]) -> None:
    try:
        registry = build_engineering_registry(root, write=False)
        ids = {entry["id"] for entry in registry["entries"]}
        for entry in registry["entries"]:
            for targets in entry.get("relationships", {}).values():
                if isinstance(targets, list):
                    for target in targets:
                        if target not in ids:
                            issues.append(_issue("BROKEN_ENGINEERING_REFERENCE", f"engineering relationship target not found: {target}", entry["registrationLocation"]))
    except Exception as exc:
        issues.append(_issue("ENGINEERING_INVALID", str(exc), "engineering"))


def _validate_integrations(
    root: Path,
    issues: list[dict[str, Any]],
    *,
    verification_session: CapabilityVerificationSession,
) -> tuple[int, Exception | None]:
    store = SchemaStore(root)
    integration_roots = sorted(path.parent for path in (root / "integrations").glob("*/integration.yaml"))
    verification_error: Exception | None = None
    for integration in integration_roots:
        try:
            loaded = load_integration(root, integration)
            control_plane = loaded["controlPlaneRoot"]
            load_project_state(root, control_plane)
            load_project_binding(root, control_plane)
            expected_lock = build_capability_lock(
                root,
                control_plane,
                write=False,
                verification_session=verification_session,
            )
            lock_path = control_plane / ".agent-evolution/capabilities.lock.yaml"
            if not lock_path.exists():
                issues.append(_issue("INTEGRATION_LOCK_MISSING", "integration capability lock missing", str(lock_path)))
            else:
                actual_lock = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
                if actual_lock != expected_lock:
                    issues.append(_issue("INTEGRATION_LOCK_DRIFT", "integration capability lock drift", str(lock_path)))
            for scenario in sorted((integration / "scenarios").glob("*.yaml")):
                value = yaml.safe_load(scenario.read_text(encoding="utf-8")) or {}
                store.validate("core/schemas/project-integration-scenario.schema.json", value)
        except Exception as exc:
            if str(exc) != "capability verification session is failed":
                verification_error = exc
            issues.append(_issue("INTEGRATION_INVALID", str(exc), str(integration)))
    return len(integration_roots), verification_error


def structural_validate(
    repository_root: Path,
    *,
    project_roots: Iterable[Path] = (),
    check_generated: bool = False,
) -> dict[str, Any]:
    root = Path(repository_root)
    external_ids = {
        registration["capabilityId"]
        for registration in load_capability_pack_registrations(root)
        if registration["status"] == "ACTIVE"
    }
    with CapabilityVerificationSession(
        root,
        allowed_capability_ids=external_ids,
    ) as verification_session:
        return _structural_validate(
            root,
            project_roots=project_roots,
            check_generated=check_generated,
            verification_session=verification_session,
        )


def _structural_validate(
    root: Path,
    *,
    project_roots: Iterable[Path],
    check_generated: bool,
    verification_session: CapabilityVerificationSession,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    base = validate_repository(root)
    for item in base.issues:
        issues.append(_issue(item.code, item.message, item.path))
    _validate_learning(root, issues)
    _validate_engineering(root, issues)

    store = SchemaStore(root)
    projects = [Path(value) for value in project_roots]
    for project in projects:
        try:
            load_project_state(root, project)
            load_project_binding(root, project)
        except Exception as exc:
            issues.append(_issue("PROJECT_CONTROL_PLANE_INVALID", str(exc), str(project)))
        handoff_path = project / ".agent-evolution/design-handoff.yaml"
        if handoff_path.exists():
            try:
                store.validate("core/schemas/design-handoff.schema.json", yaml.safe_load(handoff_path.read_text(encoding="utf-8")) or {})
            except Exception as exc:
                issues.append(_issue("HANDOFF_INVALID", str(exc), str(handoff_path)))

    if check_generated:
        try:
            _check_json_file(
                root / "generated/registries/design-registry.json",
                build_design_registry(root, write=False),
                issues,
            )
            _check_json_file(
                root / "generated/registries/design-learning-registry.json",
                build_design_learning_registry(root, write=False),
                issues,
            )
            _check_json_file(
                root / "engineering/generated/registry.json",
                build_engineering_registry(root, write=False),
                issues,
            )
            catalogs = build_all_catalogs(root, write=False)
            _check_json_file(root / "generated/catalogs/design-active-catalog.json", catalogs["design"], issues)
            _check_json_file(root / "generated/catalogs/unified-active-catalog.json", catalogs["unified"], issues)
            _check_json_file(root / "engineering/generated/active-catalog.json", catalogs["engineering"], issues)
        except Exception as exc:
            issues.append(_issue("GENERATED_CHECK_FAILED", str(exc)))
        for project in projects:
            expected_lock = build_capability_lock(
                root,
                project,
                write=False,
                verification_session=verification_session,
            )
            lock_path = project / ".agent-evolution/capabilities.lock.yaml"
            if not lock_path.exists():
                issues.append(_issue("CAPABILITY_LOCK_MISSING", "capability lock missing", str(lock_path)))
            else:
                actual_lock = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
                if actual_lock != expected_lock:
                    issues.append(_issue("CAPABILITY_LOCK_DRIFT", "capability lock differs from deterministic resolution", str(lock_path)))
            for runtime in ("CHATGPT", "CODEX"):
                check = check_projection_freshness(
                    root,
                    project,
                    runtime=runtime,
                    verification_session=verification_session,
                )
                if not check.fresh:
                    issues.append(_issue("PROJECTION_STALE", f"{runtime} projection stale: {', '.join(check.reasons)}", str(project)))

    integration_count, integration_error = _validate_integrations(
        root,
        issues,
        verification_session=verification_session,
    )
    if check_generated:
        try:
            _check_json_file(
                root / "generated/registries/capability-pack-registry.json",
                build_capability_pack_registry(
                    root,
                    write=False,
                    verification_session=verification_session,
                ),
                issues,
            )
        except Exception as exc:
            message = str(exc)
            if message == "capability verification session is failed" and integration_error:
                message = str(integration_error)
            issues.append(_issue("GENERATED_CHECK_FAILED", message))

    issues.sort(key=lambda item: (item["code"], item.get("path", ""), item["message"]))
    return {
        "schemaVersion": "structural-validation-report/v1",
        "structuralGate": "PASS" if not issues else "FAIL",
        "semanticGate": "NOT_ASSERTED_BY_CI",
        "issues": issues,
        "capabilityCount": len(build_design_registry(root, write=False)["entries"]),
        "experienceCount": sum(1 for _ in _experience_paths(root)),
        "candidateCount": sum(1 for _ in _candidate_paths(root)),
        "evalCount": len(list((root / "design/evals").glob("*.yaml"))),
        "integrationCount": integration_count,
    }
