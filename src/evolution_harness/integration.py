from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .paths import resolve_within
from .schema import SchemaStore


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_integration(repository_root: Path, integration_root: Path) -> dict[str, Any]:
    repository = Path(repository_root).resolve()
    integration = Path(integration_root).resolve()
    try:
        integration.relative_to(repository)
    except ValueError as exc:
        raise ValueError("integration config must be inside the harness repository") from exc
    config_path = integration / "integration.yaml"
    config = _load_yaml(config_path)
    store = SchemaStore(repository)
    store.validate("core/schemas/project-integration.schema.json", config)
    authority_path = resolve_within(
        integration, config["authorityMapPath"], must_exist=True, label="authority map path"
    )
    authority_map = _load_yaml(authority_path)
    store.validate("core/schemas/project-authority-map.schema.json", authority_map)
    control_plane = resolve_within(integration, config["controlPlanePath"], label="control plane path")
    return {
        "config": config,
        "authorityMap": authority_map,
        "integrationRoot": integration,
        "controlPlaneRoot": control_plane,
    }


def resolve_integration_context(
    repository_root: Path,
    integration_root: Path,
    source_root: Path,
    *,
    intent: str,
    topic: str,
    requested_output: str,
    runtime: str,
    explicit_stage: str | None = None,
    reopen_signal: str | None = None,
) -> dict[str, Any]:
    from .authority import build_authority_snapshot
    from .resolver import resolve_design_context

    loaded = load_integration(repository_root, integration_root)
    config = loaded["config"]
    if runtime != config["runtime"]:
        raise ValueError("requested runtime does not match integration runtime")
    snapshot = build_authority_snapshot(repository_root, integration_root, source_root)
    if snapshot["gate"] != "PASS":
        raise ValueError("authority snapshot gate is NO_GO")
    resolved = resolve_design_context(
        repository_root,
        loaded["controlPlaneRoot"],
        intent=intent,
        topic=topic,
        requested_output=requested_output,
        runtime=runtime,
        explicit_stage=explicit_stage,
        reopen_signal=reopen_signal,
        authority_snapshot=snapshot,
    )
    if resolved["project"] != config["projectId"]:
        raise ValueError("control-plane project does not match integration project")
    return resolved


def build_integration_projection(
    repository_root: Path,
    integration_root: Path,
    source_root: Path,
    *,
    intent: str,
    topic: str,
    requested_output: str,
    runtime: str,
    explicit_stage: str | None = None,
    reopen_signal: str | None = None,
) -> dict[str, Any]:
    from .projection import build_projection_pack

    loaded = load_integration(repository_root, integration_root)
    resolved = resolve_integration_context(
        repository_root,
        integration_root,
        source_root,
        intent=intent,
        topic=topic,
        requested_output=requested_output,
        runtime=runtime,
        explicit_stage=explicit_stage,
        reopen_signal=reopen_signal,
    )
    return build_projection_pack(
        repository_root,
        loaded["controlPlaneRoot"],
        resolved,
        runtime=runtime,
    )


def check_integration_projection(
    repository_root: Path,
    integration_root: Path,
    source_root: Path,
    *,
    runtime: str,
):
    from .authority import build_authority_snapshot
    from .projection import ProjectionFreshness, check_projection_freshness

    loaded = load_integration(repository_root, integration_root)
    if runtime != loaded["config"]["runtime"]:
        return ProjectionFreshness(False, ("integration-runtime-mismatch",))
    snapshot = build_authority_snapshot(repository_root, integration_root, source_root)
    if snapshot["gate"] != "PASS":
        return ProjectionFreshness(False, ("authority-snapshot-no-go",))
    return check_projection_freshness(
        repository_root,
        loaded["controlPlaneRoot"],
        runtime=runtime,
        authority_snapshot=snapshot,
    )
