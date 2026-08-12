from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .schema import SchemaStore


def _safe_id(value: str) -> str:
    return value.replace(":", "__")


def load_eval_definitions(repository_root: Path) -> dict[str, dict[str, Any]]:
    root = Path(repository_root)
    definitions: dict[str, dict[str, Any]] = {}
    eval_root = root / "design" / "evals"
    if not eval_root.exists():
        return definitions
    store = SchemaStore(root)
    for path in sorted(eval_root.glob("*.yaml")):
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if value.get("schemaVersion") != "design-eval/v1":
            continue
        store.validate("design/schemas/eval.schema.json", value)
        definitions[value["evalId"]] = value
    return definitions


def load_eval_results(repository_root: Path) -> list[dict[str, Any]]:
    root = Path(repository_root)
    results: list[dict[str, Any]] = []
    result_root = root / "design" / "evals" / "results"
    if not result_root.exists():
        return results
    store = SchemaStore(root)
    for path in sorted(result_root.glob("*.yaml")):
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        store.validate("design/schemas/eval-result.schema.json", value)
        results.append(value)
    return results


def record_eval_result(repository_root: Path, result: dict[str, Any]) -> Path:
    root = Path(repository_root)
    store = SchemaStore(root)
    store.validate("design/schemas/eval-result.schema.json", result)
    definitions = load_eval_definitions(root)
    definition = definitions.get(result["evalId"])
    if definition is None:
        raise ValueError(f"unknown eval definition: {result['evalId']}")
    if definition["targetCapability"] != result["capabilityId"]:
        raise ValueError(
            f"eval target mismatch: {definition['targetCapability']} != {result['capabilityId']}"
        )
    result_root = root / "design" / "evals" / "results"
    result_root.mkdir(parents=True, exist_ok=True)
    path = result_root / f"{_safe_id(result['evalResultId'])}.yaml"
    if path.exists():
        raise ValueError(f"eval result already exists: {result['evalResultId']}")
    path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def has_passing_eval(
    repository_root: Path,
    eval_id: str,
    capability_id: str,
    capability_version: str,
) -> bool:
    for result in load_eval_results(repository_root):
        if (
            result.get("evalId") == eval_id
            and result.get("capabilityId") == capability_id
            and result.get("capabilityVersion") == capability_version
            and result.get("result") == "PASS"
        ):
            return True
    return False
