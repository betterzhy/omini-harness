from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml


def _copy_repo(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    for name in ["core", "design"]:
        shutil.copytree(source / name, root / name)
    return root


def _codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


def test_seed_repository_passes_structural_governance():
    from evolution_harness.validation import validate_repository

    root = Path(__file__).parents[1]
    report = validate_repository(root)
    assert report.ok, [f"{i.code}: {i.message}" for i in report.issues]


def test_promoted_id_version_content_is_immutable(tmp_path: Path):
    from evolution_harness.validation import validate_repository

    root = _copy_repo(tmp_path)
    content = root / "design/capabilities/skills/architecture-review/content.md"
    content.write_text(content.read_text(encoding="utf-8") + "\nmutated after promotion\n", encoding="utf-8")
    report = validate_repository(root)
    assert "PROMOTED_VERSION_MUTATED" in _codes(report)


def test_duplicate_id_version_is_rejected(tmp_path: Path):
    from evolution_harness.validation import validate_repository

    root = _copy_repo(tmp_path)
    source = root / "design/capabilities/skills/architecture-review"
    shutil.copytree(source, root / "design/capabilities/skills/architecture-review-copy")
    report = validate_repository(root)
    assert "DUPLICATE_ID_VERSION" in _codes(report)


def test_broken_relationship_target_is_rejected(tmp_path: Path):
    from evolution_harness.validation import validate_repository

    root = _copy_repo(tmp_path)
    path = root / "design/capabilities/skills/architecture-review/asset.yaml"
    asset = yaml.safe_load(path.read_text(encoding="utf-8"))
    asset["relationships"]["dependsOn"].append("framework:agent-design:does-not-exist")
    path.write_text(yaml.safe_dump(asset, sort_keys=False), encoding="utf-8")
    report = validate_repository(root)
    assert "BROKEN_REFERENCE" in _codes(report)


def test_principle_cannot_depend_on_skill(tmp_path: Path):
    from evolution_harness.validation import validate_repository

    root = _copy_repo(tmp_path)
    path = root / "design/capabilities/principles/closure-requires-authority/asset.yaml"
    asset = yaml.safe_load(path.read_text(encoding="utf-8"))
    asset["relationships"]["dependsOn"] = ["skill:agent-design:architecture-review"]
    path.write_text(yaml.safe_dump(asset, sort_keys=False), encoding="utf-8")
    report = validate_repository(root)
    assert "RELATION_KIND_INVALID" in _codes(report)


def test_leaf_skill_cannot_compose_another_skill(tmp_path: Path):
    from evolution_harness.validation import validate_repository

    root = _copy_repo(tmp_path)
    path = root / "design/capabilities/skills/architecture-review/asset.yaml"
    asset = yaml.safe_load(path.read_text(encoding="utf-8"))
    asset["relationships"]["dependsOn"].append("skill:agent-design:baseline-finalization")
    path.write_text(yaml.safe_dump(asset, sort_keys=False), encoding="utf-8")
    report = validate_repository(root)
    assert "LEAF_SKILL_COMPOSITION" in _codes(report)


def test_orchestration_skill_cycle_is_rejected(tmp_path: Path):
    from evolution_harness.validation import validate_repository

    root = _copy_repo(tmp_path)
    a = root / "design/capabilities/skills/architecture-review/asset.yaml"
    b = root / "design/capabilities/skills/baseline-finalization/asset.yaml"
    aa = yaml.safe_load(a.read_text(encoding="utf-8"))
    bb = yaml.safe_load(b.read_text(encoding="utf-8"))
    aa["skill"]["skillRole"] = "ORCHESTRATION"
    bb["skill"]["skillRole"] = "ORCHESTRATION"
    aa["relationships"]["dependsOn"].append("skill:agent-design:baseline-finalization")
    bb["relationships"]["dependsOn"].append("skill:agent-design:architecture-review")
    a.write_text(yaml.safe_dump(aa, sort_keys=False), encoding="utf-8")
    b.write_text(yaml.safe_dump(bb, sort_keys=False), encoding="utf-8")
    report = validate_repository(root)
    assert "RELATION_CYCLE" in _codes(report)


def test_orchestration_skill_composition_is_bounded():
    from evolution_harness.relations import validate_skill_composition

    asset = {
        "id": "skill:agent-design:orchestrator",
        "kind": "SKILL",
        "skill": {"skillRole": "ORCHESTRATION", "referencedCapabilities": [f"skill:agent-design:s{i}" for i in range(4)]},
        "relationships": {"dependsOn": [f"skill:agent-design:d{i}" for i in range(3)]},
    }
    issues = validate_skill_composition(asset, max_skill_dependencies=6)
    assert any(issue.code == "SKILL_COMPOSITION_BOUND" for issue in issues)


def test_promoted_versions_can_coexist_without_mutating_history(tmp_path: Path):
    from evolution_harness.loader import load_capabilities
    from evolution_harness.validation import validate_repository

    root = _copy_repo(tmp_path)
    source = root / "design/capabilities/skills/architecture-review"
    target = root / "design/capabilities/skills/architecture-review-v1-1"
    shutil.copytree(source, target)
    path = target / "asset.yaml"
    asset = yaml.safe_load(path.read_text(encoding="utf-8"))
    asset["version"] = "1.1.0"
    path.write_text(yaml.safe_dump(asset, sort_keys=False), encoding="utf-8")

    new_capability = next(c for c in load_capabilities(root) if c.id == asset["id"] and c.version == "1.1.0")
    ledger_path = root / "core/governance/promotion-ledger.yaml"
    ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8"))
    ledger["entries"].append({
        "capabilityId": new_capability.id,
        "version": new_capability.version,
        "contentHash": new_capability.content_hash,
        "authorization": "PROMOTED",
        "authorizedAt": "2026-08-11T00:00:00Z",
        "authorityDecision": "APPROVE",
        "sourceReference": "candidate://fixture"
    })
    ledger_path.write_text(yaml.safe_dump(ledger, sort_keys=False), encoding="utf-8")

    report = validate_repository(root)
    assert "MULTIPLE_ACTIVE_VERSIONS" not in _codes(report)
    assert report.ok, [f"{i.code}: {i.message}" for i in report.issues]


def test_every_canonical_version_requires_bootstrap_or_promotion_ledger_entry(tmp_path: Path):
    from evolution_harness.validation import validate_repository

    root = _copy_repo(tmp_path)
    ledger_path = root / "core/governance/promotion-ledger.yaml"
    ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8"))
    ledger["entries"] = ledger["entries"][1:]
    ledger_path.write_text(yaml.safe_dump(ledger, sort_keys=False), encoding="utf-8")
    report = validate_repository(root)
    assert "UNAUTHORIZED_CANONICAL_VERSION" in _codes(report)


def test_identity_kind_mismatch_is_rejected(tmp_path: Path):
    from evolution_harness.validation import validate_repository

    root = _copy_repo(tmp_path)
    path = root / "design/capabilities/skills/architecture-review/asset.yaml"
    asset = yaml.safe_load(path.read_text(encoding="utf-8"))
    asset["kind"] = "FRAMEWORK"
    path.write_text(yaml.safe_dump(asset, sort_keys=False), encoding="utf-8")
    report = validate_repository(root)
    assert "IDENTITY_KIND_MISMATCH" in _codes(report)
