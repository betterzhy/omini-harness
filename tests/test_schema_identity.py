from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_parse_capability_id_accepts_stable_identity():
    from evolution_harness.identity import parse_capability_id

    parsed = parse_capability_id("skill:agent-design:architecture-review")
    assert parsed.kind == "skill"
    assert parsed.namespace == "agent-design"
    assert parsed.name == "architecture-review"


@pytest.mark.parametrize(
    "value",
    [
        "skill:agent-design",
        "skill::architecture-review",
        ":agent-design:architecture-review",
        "unknown:agent-design:x",
        "skill:agent design:x",
        "skill:agent-design:x:y",
    ],
)
def test_parse_capability_id_rejects_invalid_identity(value: str):
    from evolution_harness.identity import IdentityError, parse_capability_id

    with pytest.raises(IdentityError):
        parse_capability_id(value)


@pytest.mark.parametrize("value", ["0.1.0", "1.0.0", "12.34.56"])
def test_semver_accepts_strict_three_part_versions(value: str):
    from evolution_harness.identity import validate_semver

    assert validate_semver(value) == value


@pytest.mark.parametrize("value", ["1", "1.0", "v1.0.0", "1.0.0-alpha", "01.0.0"])
def test_semver_rejects_non_mvp_forms(value: str):
    from evolution_harness.identity import VersionError, validate_semver

    with pytest.raises(VersionError):
        validate_semver(value)


def test_schema_store_validates_common_and_kind_specific_skill(tmp_path: Path):
    from evolution_harness.schema import SchemaStore

    root = Path(__file__).parents[1]
    store = SchemaStore(root)
    asset = {
        "schemaVersion": "design-capability/v1",
        "id": "skill:agent-design:test-skill",
        "kind": "SKILL",
        "version": "1.0.0",
        "title": "Test skill",
        "summary": "Small test skill",
        "lifecycle": "ACTIVE",
        "validity": "VALID",
        "scope": {"intent": ["architecture-review"], "stage": ["CALIBRATION"], "runtime": ["CHATGPT"]},
        "modelSensitivity": "MODEL_INDEPENDENT",
        "visibility": "SHARED",
        "provenance": [{"sourceType": "HUMAN_REVIEW", "reference": "review://fixture", "visibility": "SHARED"}],
        "relationships": {"dependsOn": [], "extends": [], "derivedFrom": [], "supersedes": [], "constrainedBy": []},
        "evalBindings": [],
        "contentFile": "content.md",
        "skill": {
            "skillRole": "LEAF",
            "intent": ["architecture-review"],
            "triggers": ["review architecture"],
            "whenNotToUse": [],
            "requiredContext": ["project-state"],
            "referencedCapabilities": [],
            "humanGates": [],
            "outputContract": ["findings"],
            "stopConditions": ["scope complete"],
            "selfReview": ["check authority"],
        },
    }
    store.validate("design/schemas/skill.schema.json", asset)


def test_schema_store_rejects_unknown_unprefixed_field():
    from evolution_harness.schema import SchemaStore, SchemaValidationError

    root = Path(__file__).parents[1]
    store = SchemaStore(root)
    asset = {
        "schemaVersion": "design-capability/v1",
        "id": "skill:agent-design:test-skill",
        "kind": "SKILL",
        "version": "1.0.0",
        "title": "Test skill",
        "summary": "Small test skill",
        "lifecycle": "ACTIVE",
        "validity": "VALID",
        "scope": {},
        "modelSensitivity": "MODEL_INDEPENDENT",
        "visibility": "SHARED",
        "provenance": [{"sourceType": "HUMAN_REVIEW", "reference": "review://fixture", "visibility": "SHARED"}],
        "relationships": {"dependsOn": [], "extends": [], "derivedFrom": [], "supersedes": [], "constrainedBy": []},
        "evalBindings": [],
        "contentFile": "content.md",
        "skill": {
            "skillRole": "LEAF",
            "intent": ["architecture-review"],
            "triggers": ["review architecture"],
            "whenNotToUse": [],
            "requiredContext": [],
            "referencedCapabilities": [],
            "humanGates": [],
            "outputContract": ["findings"],
            "stopConditions": ["complete"],
            "selfReview": ["check"],
        },
        "mystery": True,
    }
    with pytest.raises(SchemaValidationError):
        store.validate("design/schemas/skill.schema.json", asset)


def test_vocabulary_contains_required_stage_runtime_and_model_values():
    import yaml

    root = Path(__file__).parents[1]
    vocabulary = yaml.safe_load((root / "core" / "vocabulary" / "v1.yaml").read_text(encoding="utf-8"))
    assert "REPOSITORY_LANDING" in vocabulary["designStages"]
    assert {"CHATGPT", "CODEX", "GENERIC_AGENT"}.issubset(vocabulary["runtimes"])
    assert {"MODEL_INDEPENDENT", "MODEL_SENSITIVE", "MODEL_SPECIFIC"}.issubset(vocabulary["modelSensitivity"])
