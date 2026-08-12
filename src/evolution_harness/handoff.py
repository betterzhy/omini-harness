from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .hashing import canonical_json_bytes, sha256_bytes
from .project import load_project_state
from .schema import SchemaStore


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _stable_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def build_design_handoff(repository_root: Path, project_root: Path, *, write: bool = False) -> dict[str, Any]:
    root = Path(repository_root)
    project = Path(project_root)
    store = SchemaStore(root)
    state = load_project_state(root, project)
    input_path = project / ".agent-evolution" / "handoff-input.yaml"
    handoff_input = _load_yaml(input_path)
    store.validate("core/schemas/design-handoff-input.schema.json", handoff_input)

    protected_decisions = list(state.get("protectedDecisions", []))
    decision_references = _stable_unique(list(state.get("openDecisions", [])) + protected_decisions)
    source_model = {"designState": state, "handoffInput": handoff_input}
    source_revision = "content-sha256:" + sha256_bytes(canonical_json_bytes(source_model))

    canonical_fields = {
        "baselineReferences": list(state.get("baselines", [])),
        "decisionReferences": decision_references,
        "authorityReferences": list(state.get("projectAuthorityReferences", [])),
        "assumptionReferences": list(state.get("assumptions", [])),
    }
    input_fields = {
        "entityReferences": handoff_input["entityReferences"],
        "invariantReferences": handoff_input["invariantReferences"],
        "protectedBoundaryReferences": handoff_input["protectedBoundaryReferences"],
        "externalContractReferences": handoff_input["externalContractReferences"],
        "implementationConstraints": handoff_input["implementationConstraints"],
        "openEngineeringQuestions": handoff_input["openEngineeringQuestions"],
        "verificationObligations": handoff_input["verificationObligations"],
        "reopenConditions": handoff_input["reopenConditions"],
    }
    field_authority = {field: "PROJECT_CANONICAL_REFERENCE" for field in canonical_fields}
    field_authority.update({field: "PROJECT_HANDOFF_INPUT" for field in input_fields})
    field_authority["sourceRevision"] = "GENERATED_PROJECTION"

    result: dict[str, Any] = {
        "schemaVersion": "design-handoff/v1",
        "project": state["project"],
        **canonical_fields,
        **input_fields,
        "sourceRevision": source_revision,
        "fieldAuthority": field_authority,
    }
    store.validate("core/schemas/design-handoff.schema.json", result)
    if write:
        path = project / ".agent-evolution" / "design-handoff.yaml"
        path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return result
