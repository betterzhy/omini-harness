from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml


EXTERNAL_CAPABILITY_ID = "workflow:web-high-fidelity:reference-driven-visual-fidelity"


def _copy_repo(tmp_path: Path) -> tuple[Path, Path]:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    for name in ["core", "design", "runtime", "examples"]:
        src = source / name
        if src.exists():
            shutil.copytree(src, root / name)
    return root, root / "examples/project-fixture"


def _project_selecting_registered_pack(tmp_path: Path) -> tuple[Path, Path]:
    root, project = _copy_repo(tmp_path)
    binding_path = project / ".agent-evolution/capabilities.yaml"
    binding = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
    binding["capabilities"].append(EXTERNAL_CAPABILITY_ID)
    binding_path.write_text(yaml.safe_dump(binding, sort_keys=False), encoding="utf-8")
    return root, project


def test_project_fixture_state_and_binding_validate():
    from evolution_harness.schema import SchemaStore

    root = Path(__file__).parents[1]
    store = SchemaStore(root)
    project = root / "examples/project-fixture/.agent-evolution"
    state = yaml.safe_load((project / "design-state.yaml").read_text(encoding="utf-8"))
    binding = yaml.safe_load((project / "capabilities.yaml").read_text(encoding="utf-8"))
    store.validate("core/schemas/project-design-state.schema.json", state)
    store.validate("core/schemas/project-capability-binding.schema.json", binding)
    closed = next(t for t in state["topics"] if t["status"] == "CLOSED")
    assert {"closedAt", "closedBy", "baselineReference", "reopenConditions"} <= set(closed)


def test_closed_topic_schema_requires_authority_and_reopen_metadata():
    from evolution_harness.schema import SchemaStore, SchemaValidationError

    root = Path(__file__).parents[1]
    value = {
        "schemaVersion": "project-design-state/v1",
        "project": "x",
        "currentStage": "CALIBRATION",
        "topics": [{"topicId": "closed", "status": "CLOSED", "scope": {}}],
        "baselines": [], "assumptions": [], "openDecisions": [], "nextTopicCandidates": [],
        "projectAuthorityReferences": [], "protectedDecisions": [], "projectConstraints": []
    }
    with pytest.raises(SchemaValidationError):
        SchemaStore(root).validate("core/schemas/project-design-state.schema.json", value)


def test_capability_lock_is_exact_and_traceable(tmp_path: Path):
    from evolution_harness.project import build_capability_lock

    root, project = _copy_repo(tmp_path)
    lock = build_capability_lock(root, project, write=True)
    assert lock["schemaVersion"] == "capability-lock/v1"
    assert len(lock["capabilities"]) == 10
    assert all({"capabilityId", "resolvedVersion", "contentHash", "sourceHarnessRevision"} <= set(item) for item in lock["capabilities"])
    assert all(item["resolvedVersion"].count(".") == 2 for item in lock["capabilities"])
    stored = yaml.safe_load((project / ".agent-evolution/capabilities.lock.yaml").read_text(encoding="utf-8"))
    assert stored == lock


def test_internal_only_lock_is_byte_stable_without_external_packs(tmp_path: Path):
    from evolution_harness.hashing import canonical_json_bytes
    from evolution_harness.project import build_capability_lock

    root, project = _copy_repo(tmp_path)
    persisted_v1 = yaml.safe_load(
        (project / ".agent-evolution/capabilities.lock.yaml").read_text(encoding="utf-8")
    )

    lock = build_capability_lock(root, project, write=True)

    assert lock["schemaVersion"] == "capability-lock/v1"
    assert canonical_json_bytes(lock) == canonical_json_bytes(persisted_v1)


def test_external_pack_binding_generates_v2_exact_lock(tmp_path: Path):
    from evolution_harness.capability_pack_registry import build_capability_pack_registry
    from evolution_harness.hashing import canonical_json_bytes, sha256_bytes
    from evolution_harness.project import build_capability_lock, verify_capability_lock

    root, project = _project_selecting_registered_pack(tmp_path)
    registration = build_capability_pack_registry(root, write=False)["entries"][0]

    lock = build_capability_lock(root, project, write=True)

    assert lock["schemaVersion"] == "capability-lock/v2"
    item = next(
        item
        for item in lock["capabilities"]
        if item["sourceKind"] == "EXTERNAL_CAPABILITY_PACK"
    )
    assert item["sourceRegistrationId"] == registration["registrationId"]
    assert item["sourceCommit"] == registration["source"]["commit"]
    assert item["sourceTree"] == registration["source"]["tree"]
    assert item["resolvedContentDigest"] == registration["resolvedContentDigest"]
    assert item["contentHash"] == registration["resolvedContentDigest"].removeprefix(
        "sha256:"
    )
    assert item["validatorIdentity"] == {
        "relativePath": registration["validator"]["relativePath"],
        "sha256": registration["validator"]["sha256"],
    }
    assert item["registrationFingerprint"] == (
        "sha256:" + sha256_bytes(canonical_json_bytes(registration))
    )
    verified_result = verify_capability_lock(root, project)
    assert isinstance(verified_result, tuple) and len(verified_result) == 2
    _, verified = verified_result
    assert verified[EXTERNAL_CAPABILITY_ID]["sourceKind"] == "EXTERNAL_CAPABILITY_PACK"
    assert verified[EXTERNAL_CAPABILITY_ID]["registrationId"] == registration[
        "registrationId"
    ]
    assert verified[EXTERNAL_CAPABILITY_ID]["manifest"]["skillPath"] == (
        "skills/web-high-fidelity/SKILL.md"
    )
    assert all(
        item["sourceKind"] == "HARNESS_CANONICAL"
        for item in lock["capabilities"]
        if item["capabilityId"] != EXTERNAL_CAPABILITY_ID
    )


def _allow_registration_variants(root: Path) -> None:
    schema_path = root / "core/schemas/capability-pack-registration.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["properties"]["registrationId"] = {
        "type": "string",
        "pattern": "^pack:[a-z0-9-]+$",
    }
    schema["properties"]["status"] = {"enum": ["ACTIVE", "INACTIVE"]}
    schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")


def test_external_pack_binding_rejects_missing_active_registration(tmp_path: Path):
    from evolution_harness.project import build_capability_lock

    root, project = _project_selecting_registered_pack(tmp_path)
    _allow_registration_variants(root)
    registry_path = root / "core/registries/capability-packs.yaml"
    registrations = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registrations[0]["status"] = "INACTIVE"
    registry_path.write_text(
        yaml.safe_dump(registrations, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(
        ValueError, match="active capability pack registration not found or ambiguous"
    ):
        build_capability_lock(root, project, write=False)


def test_external_pack_binding_rejects_duplicate_active_capability_ids(tmp_path: Path):
    from evolution_harness.project import build_capability_lock

    root, project = _project_selecting_registered_pack(tmp_path)
    _allow_registration_variants(root)
    registry_path = root / "core/registries/capability-packs.yaml"
    registrations = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    duplicate = yaml.safe_load(yaml.safe_dump(registrations[0]))
    duplicate["registrationId"] = "pack:web-high-fidelity-duplicate"
    registry_path.write_text(
        yaml.safe_dump([registrations[0], duplicate], sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="duplicate active capability pack ID"):
        build_capability_lock(root, project, write=False)


def test_unrelated_registry_entry_does_not_move_selected_external_lock(tmp_path: Path):
    from evolution_harness.project import build_capability_lock

    root, project = _project_selecting_registered_pack(tmp_path)
    before = build_capability_lock(root, project, write=False)
    _allow_registration_variants(root)
    registry_path = root / "core/registries/capability-packs.yaml"
    registrations = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    inactive = yaml.safe_load(yaml.safe_dump(registrations[0]))
    inactive["registrationId"] = "pack:web-high-fidelity-archive"
    inactive["status"] = "INACTIVE"
    registry_path.write_text(
        yaml.safe_dump([registrations[0], inactive], sort_keys=False), encoding="utf-8"
    )

    after = build_capability_lock(root, project, write=False)

    assert after == before


def test_project_design_state_rejects_path_like_project_identity(tmp_path: Path):
    from evolution_harness.project import load_project_state
    from evolution_harness.schema import SchemaValidationError

    root, project = _copy_repo(tmp_path)
    state_path = project / ".agent-evolution/design-state.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["project"] = str(tmp_path / "victim")
    state_path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")

    with pytest.raises(SchemaValidationError):
        load_project_state(root, project)


def test_project_design_state_rejects_duplicate_topic_ids(tmp_path: Path):
    from evolution_harness.project import load_project_state

    root, project = _copy_repo(tmp_path)
    state_path = project / ".agent-evolution/design-state.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    duplicate = dict(state["topics"][0])
    duplicate["status"] = "OPEN"
    duplicate.pop("closedAt", None)
    duplicate.pop("closedBy", None)
    duplicate.pop("baselineReference", None)
    duplicate.pop("reopenConditions", None)
    state["topics"].insert(0, duplicate)
    state_path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate topic"):
        load_project_state(root, project)
