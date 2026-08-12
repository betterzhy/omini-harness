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
