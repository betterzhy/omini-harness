from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import yaml

from evolution_harness.schema import SchemaStore


CAPABILITY_ID = "framework:java:java-engineering-standard"
REGISTRATION_ID = "pack:java-engineering-standard"
SOURCE_COMMIT = "01d0e7d15ef9f6aa7814b0b001fa0b7c2c30e882"
SOURCE_TREE = "4bfc51d75c9e01e585db4cc073f952043ea01393"
CONTENT_DIGEST = "sha256:4e5920ddd604d7905647af94eb460f7ab20124fb96ffdea73f50ed6efd5a4581"
RESOURCE_SET_DIGEST = "sha256:0ae349a6e13c367759774c12d84f83ae14db782f2bea8f5b0fe6406748c82539"
PAY_SOURCE = Path("/Users/yuzhuangzhuang/Projects/pay-nexus/.worktrees/java-capability-adoption-pilot")


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _git_state(path: Path) -> tuple[bytes, bytes, bytes]:
    head_tree = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD", "HEAD^{tree}"],
        check=True,
        capture_output=True,
    ).stdout.splitlines()
    status = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain=v1", "-z"],
        check=True,
        capture_output=True,
    ).stdout
    return head_tree[0], head_tree[1], status


def test_pay_nexus_sidecar_binds_exact_java_v2_lock():
    root = Path(__file__).parents[1]
    control = root / "integrations/pay-nexus-shadow/control-plane/.agent-evolution"
    binding = _yaml(control / "capabilities.yaml")
    lock = _yaml(control / "capabilities.lock.yaml")
    SchemaStore(root).validate("core/schemas/capability-lock.schema.json", lock)
    assert CAPABILITY_ID in binding["capabilities"]
    assert lock["schemaVersion"] == "capability-lock/v2"
    java = next(item for item in lock["capabilities"] if item["capabilityId"] == CAPABILITY_ID)
    assert java["sourceRegistrationId"] == REGISTRATION_ID
    assert java["sourceCommit"] == SOURCE_COMMIT
    assert java["sourceTree"] == SOURCE_TREE
    assert java["resolvedContentDigest"] == CONTENT_DIGEST
    assert java["validatorIdentity"]["gitHistoryContract"] == "CANDIDATE_PARENT_TREE"


def test_pay_registration_matches_lock_and_pilot_is_orthogonal():
    root = Path(__file__).parents[1]
    lock = _yaml(root / "integrations/pay-nexus-shadow/control-plane/.agent-evolution/capabilities.lock.yaml")
    registration = _yaml(PAY_SOURCE / ".agent-evolution/registration.yaml")
    progress = (PAY_SOURCE / "docs/architecture/engineering-readiness/java-capability-adoption-pilot-progress.md").read_text(encoding="utf-8")
    status = (PAY_SOURCE / "current-formal-status.md").read_text(encoding="utf-8")
    assert registration["capabilityLockFingerprint"] == lock["lockFingerprint"]
    assert "TaskCardId = JCA-PILOT-RT-001" in progress
    assert "ActiveDevelopmentSliceCount = 0" in progress
    assert "SkillInstallAllowed = NO" in progress
    assert "TempInputAccessAllowed = NO" in progress
    assert "ActiveEngineeringGovernanceSlice = PAY_NEXUS_PHASE3D_DUAL_LANE_EXECUTION" in status
    assert "JavaCapabilityPilotProgressAuthority = docs/architecture/engineering-readiness/java-capability-adoption-pilot-progress.md" in status


def test_pay_nexus_projection_contains_byte_identical_java_bundle():
    root = Path(__file__).parents[1]
    pack = root / "generated/projections/codex/pay-nexus-shadow"
    manifest = json.loads((pack / "projection-manifest.json").read_text(encoding="utf-8"))
    SchemaStore(root).validate("core/schemas/runtime-projection-manifest.schema.json", manifest)
    generated = next(item for item in manifest["generatedSkills"] if item["id"] == CAPABILITY_ID)
    assert generated["projectionContract"] == "SELF_CONTAINED_SKILL_BUNDLE"
    assert generated["resourceSetDigest"] == RESOURCE_SET_DIGEST
    assert len(generated["resourceFiles"]) == 45
    assert len({item["sourcePath"] for item in generated["resourceFiles"]}) == 45
    for resource in generated["resourceFiles"]:
        target = (pack / resource["path"]).read_bytes()
        source = subprocess.run(
            ["git", "-C", "/Users/yuzhuangzhuang/Projects/java-engineering-standard", "show", f"{SOURCE_COMMIT}:{resource['sourcePath']}"],
            check=True,
            capture_output=True,
        ).stdout
        assert target == source
        assert hashlib.sha256(target).hexdigest() == resource["sha256"]
    assert "skill:agent-design:architecture-review" in {item["id"] for item in manifest["generatedSkills"]}
    assert not any("temp-input" in item["path"] for item in manifest["generatedFiles"])


def test_pay_nexus_scenarios_and_install_plan_remain_read_only(tmp_path: Path):
    from evolution_harness.install import install_projection
    from evolution_harness.scenario import run_integration_scenario

    root = Path(__file__).parents[1]
    integration = root / "integrations/pay-nexus-shadow"
    before = _git_state(PAY_SOURCE)
    results = [
        run_integration_scenario(root, integration, PAY_SOURCE, scenario)
        for scenario in sorted((integration / "scenarios").glob("*.yaml"))
    ]
    assert len(results) == 6
    failures = {
        result["scenarioId"]: [check for check in result["checks"] if not check["pass"]]
        for result in results
        if result["gate"] != "PASS"
    }
    assert failures == {}
    target = tmp_path / "dry-run-target"
    target.mkdir()
    plan = install_projection(
        root,
        root / "generated/projections/codex/pay-nexus-shadow",
        target,
        source_root=PAY_SOURCE,
    )
    assert plan["gate"] == "PASS"
    assert plan["mode"] == "DRY_RUN"
    assert len(plan["actions"]) == 46
    assert before == _git_state(PAY_SOURCE)
