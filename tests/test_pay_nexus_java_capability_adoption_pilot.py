from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from evolution_harness.schema import SchemaStore
from evolution_harness.scenario import run_integration_scenario


CAPABILITY_ID = "framework:java:java-engineering-standard"
REGISTRATION_ID = "pack:java-engineering-standard"
SOURCE_COMMIT = "01d0e7d15ef9f6aa7814b0b001fa0b7c2c30e882"
SOURCE_TREE = "4bfc51d75c9e01e585db4cc073f952043ea01393"
CONTENT_DIGEST = "sha256:4e5920ddd604d7905647af94eb460f7ab20124fb96ffdea73f50ed6efd5a4581"
RESOURCE_SET_DIGEST = "sha256:0ae349a6e13c367759774c12d84f83ae14db782f2bea8f5b0fe6406748c82539"
LOCK_FINGERPRINT = "sha256:cec81d28e8f6b015fa824db42bd0624d8cca7fa58c52a31ac6a220fbbf49936c"
REGISTRATION_FINGERPRINT = "sha256:5257755a93fafa35f7cb40fcdcd0a50aaf829ec66848e50c8c3e5db9a879e92b"
AUTHORITY_SNAPSHOT_FINGERPRINT = "sha256:75fe45f728f16d256ccdf88608f6a4a8fb98e6ea0c023da3cb5987eb4e6a0c32"
AUTHORITY_SET_DIGEST = "sha256:ff784fe6b77325eaa793004853ada8e693f886ae434a0983d083bf1f0cc12e48"
PAY_REPOSITORY = Path("/Users/yuzhuangzhuang/Projects/pay-nexus")
PAY_SOURCE_COMMIT = "8252b746461ed9be40429739d66efea78151ee4d"
PAY_SOURCE_TREE = "4c8ff242aa2fc436a9f0387a650a7f868d559c9a"
EXPECTED_REGISTRATION_DRIFT = (
    "external capability pack lock registration drift: "
    "framework:java:java-engineering-standard"
)


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


@pytest.fixture(scope="module")
def pay_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("pay-source") / "repository"
    subprocess.run(
        ["git", "clone", "-q", "--no-checkout", "--local", str(PAY_REPOSITORY), str(target)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(target), "checkout", "-q", "--detach", PAY_SOURCE_COMMIT],
        check=True,
        capture_output=True,
    )
    assert _git_state(target) == (
        PAY_SOURCE_COMMIT.encode(),
        PAY_SOURCE_TREE.encode(),
        b"",
    )
    return target


def test_pay_nexus_sidecar_binds_exact_java_v2_lock():
    root = Path(__file__).parents[1]
    control = root / "integrations/pay-nexus-shadow/control-plane/.agent-evolution"
    binding = _yaml(control / "capabilities.yaml")
    lock = _yaml(control / "capabilities.lock.yaml")
    SchemaStore(root).validate("core/schemas/capability-lock.schema.json", lock)
    assert CAPABILITY_ID in binding["capabilities"]
    assert lock["schemaVersion"] == "capability-lock/v2"
    assert lock["lockFingerprint"] == LOCK_FINGERPRINT
    java = next(item for item in lock["capabilities"] if item["capabilityId"] == CAPABILITY_ID)
    assert java["registrationFingerprint"] == REGISTRATION_FINGERPRINT
    assert java["sourceRegistrationId"] == REGISTRATION_ID
    assert java["sourceCommit"] == SOURCE_COMMIT
    assert java["sourceTree"] == SOURCE_TREE
    assert java["resolvedContentDigest"] == CONTENT_DIGEST
    assert java["validatorIdentity"]["gitHistoryContract"] == "CANDIDATE_PARENT_TREE"


def test_pay_registration_matches_lock_and_pilot_is_orthogonal(pay_source: Path):
    root = Path(__file__).parents[1]
    lock = _yaml(root / "integrations/pay-nexus-shadow/control-plane/.agent-evolution/capabilities.lock.yaml")
    registration = _yaml(pay_source / ".agent-evolution/registration.yaml")
    progress = (pay_source / "docs/architecture/engineering-readiness/java-capability-adoption-pilot-progress.md").read_text(encoding="utf-8")
    status = (pay_source / "current-formal-status.md").read_text(encoding="utf-8")
    assert registration["capabilityLockFingerprint"] == lock["lockFingerprint"]
    assert "TaskCardId = JCA-PILOT-RT-001" in progress
    assert "Status = CLOSED_FINAL_CLOSURE_REVIEWED_GO_AUTHORIZATION_CONSUMED" in progress
    assert "TaskCardStatus = CLOSED_REVIEWED_GO" in progress
    assert "CurrentGate = JCA_PILOT_FINAL_CLOSURE_REVIEWED_GO" in progress
    assert (
        "NextRequiredAction = "
        "AWAIT_SEPARATE_PHASE3D_REBIND_AND_DEVELOPMENT_ADMISSION_TASK"
        in progress
    )
    assert (
        "NextGate = "
        "NONE_AWAIT_SEPARATE_PHASE3D_REBIND_AND_DEVELOPMENT_ADMISSION_TASK"
        in progress
    )
    assert "Status = AUTHORIZED_CONFIGURATION_TDD" not in progress
    assert "NextRequiredAction = BUILD_EXACT_V2_LOCK_AND_CODEX_PROJECTION" not in progress
    assert "ActiveDevelopmentSliceCount = 0" in progress
    assert "SkillInstallAllowed = NO" in progress
    assert "JavaStandardComplianceClaimAllowed = NO" in progress
    assert "Phase3DRebindAuthorized = NO" in progress
    assert "DevelopmentAdmissionAuthorized = NO" in progress
    assert "TempInputAccessAllowed = NO" in progress
    assert "ActiveEngineeringGovernanceSlice = PAY_NEXUS_PHASE3D_DUAL_LANE_EXECUTION" in status
    assert (
        "JavaCapabilityPilotStatus = "
        "CLOSED_FINAL_CLOSURE_REVIEWED_GO_AUTHORIZATION_CONSUMED"
        in status
    )
    assert (
        "JavaCapabilityPilotCurrentGate = JCA_PILOT_FINAL_CLOSURE_REVIEWED_GO"
        in status
    )
    assert "CurrentDevelopmentAdmissionStage = PHASE3D_DUAL_LANE_EXECUTION_AUTHORITY_CANDIDATE_PENDING_REVIEW" in status
    assert "JavaCapabilityPilotProgressAuthority = docs/architecture/engineering-readiness/java-capability-adoption-pilot-progress.md" in status


def test_pay_nexus_projection_contains_byte_identical_java_bundle():
    root = Path(__file__).parents[1]
    pack = root / "generated/projections/codex/pay-nexus-shadow"
    lock = _yaml(root / "integrations/pay-nexus-shadow/control-plane/.agent-evolution/capabilities.lock.yaml")
    locked_java = next(item for item in lock["capabilities"] if item["capabilityId"] == CAPABILITY_ID)
    manifest = json.loads((pack / "projection-manifest.json").read_text(encoding="utf-8"))
    SchemaStore(root).validate("core/schemas/runtime-projection-manifest.schema.json", manifest)
    assert manifest["capabilityLockFingerprint"] == LOCK_FINGERPRINT
    assert manifest["authoritySnapshotFingerprint"] == AUTHORITY_SNAPSHOT_FINGERPRINT
    assert manifest["authoritySourceRevision"]["kind"] == "GIT"
    assert manifest["authoritySourceRevision"]["head"] == PAY_SOURCE_COMMIT
    assert manifest["authoritySourceRevision"]["tree"] == PAY_SOURCE_TREE
    assert manifest["authoritySourceRevision"]["authoritySetStatus"] == "CLEAN_FOR_AUTHORITY_SET"
    assert manifest["authoritySourceRevision"]["authoritySetDigest"] == AUTHORITY_SET_DIGEST
    generated = next(item for item in manifest["generatedSkills"] if item["id"] == CAPABILITY_ID)
    assert generated["projectionContract"] == "SELF_CONTAINED_SKILL_BUNDLE"
    assert generated["sourceRegistrationId"] == REGISTRATION_ID
    assert generated["sourceCommit"] == SOURCE_COMMIT
    assert generated["sourceTree"] == SOURCE_TREE
    assert generated["resolvedContentDigest"] == CONTENT_DIGEST
    assert generated["registrationFingerprint"] == REGISTRATION_FINGERPRINT
    assert generated["validatorIdentity"] == locked_java["validatorIdentity"]
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


@pytest.mark.integration
@pytest.mark.pack_e2e
def test_pay_nexus_real_integration_fails_closed_on_exact_registration_drift(
    pay_source: Path,
):
    from evolution_harness.capability_pack_registry import (
        CapabilityVerificationSession,
        get_registered_capability_pack,
    )
    from evolution_harness.project import _ExternalCapabilityLockRegistrationDrift

    root = Path(__file__).parents[1]
    integration = root / "integrations/pay-nexus-shadow"
    before = _git_state(pay_source)
    with CapabilityVerificationSession(
        root,
        allowed_capability_ids={CAPABILITY_ID},
    ) as session:
        get_registered_capability_pack(
            root,
            CAPABILITY_ID,
            verification_session=session,
        )
        before_scenario = session.stats
        assert before_scenario.full_candidate_gate_count == 1
        assert before_scenario.isolated_checkout_count == 1
        assert before_scenario.toolchain_directory_digest_count == 6
        assert before_scenario.verified_pack_count == 1
        assert before_scenario.verified_lock_count == 0
        assert before_scenario.pack_reuse_hit_count == 0
        assert before_scenario.lock_reuse_hit_count == 0
        assert before_scenario.source_recheck_count == 1
        assert before_scenario.registration_recheck_count == 1
        assert before_scenario.lock_witness_recheck_count == 0
        assert before_scenario.active_use_lease_count == 0
        checkout = next(iter(session._verified.values()))._checkout_root
        assert checkout.exists()

        with pytest.raises(
            _ExternalCapabilityLockRegistrationDrift
        ) as exc_info:
            run_integration_scenario(
                root,
                integration,
                pay_source,
                integration / "scenarios/current-authority-denies-execution.yaml",
                verification_session=session,
            )
        assert str(exc_info.value) == EXPECTED_REGISTRATION_DRIFT
        after_scenario = session.stats
        assert (
            after_scenario.full_candidate_gate_count,
            after_scenario.isolated_checkout_count,
            after_scenario.toolchain_directory_digest_count,
            after_scenario.verified_pack_count,
        ) == (
            before_scenario.full_candidate_gate_count,
            before_scenario.isolated_checkout_count,
            before_scenario.toolchain_directory_digest_count,
            before_scenario.verified_pack_count,
        )
        assert after_scenario.verified_lock_count == (
            before_scenario.verified_lock_count
        )
        assert after_scenario.pack_reuse_hit_count == (
            before_scenario.pack_reuse_hit_count + 1
        )
        assert after_scenario.lock_reuse_hit_count == (
            before_scenario.lock_reuse_hit_count
        )
        assert after_scenario.source_recheck_count == (
            before_scenario.source_recheck_count + 1
        )
        assert after_scenario.registration_recheck_count == (
            before_scenario.registration_recheck_count + 1
        )
        assert after_scenario.lock_witness_recheck_count == (
            before_scenario.lock_witness_recheck_count
        )
        assert after_scenario.active_use_lease_count == 0
        assert before == _git_state(pay_source)
    assert session.stats.active_use_lease_count == 0
    assert not checkout.exists()
