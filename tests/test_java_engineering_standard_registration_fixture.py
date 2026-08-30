from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from evolution_harness.install import install_projection
from evolution_harness.schema import SchemaStore


CAPABILITY_ID = "framework:java:java-engineering-standard"
REGISTRATION_ID = "pack:java-engineering-standard"
SOURCE_COMMIT = "01d0e7d15ef9f6aa7814b0b001fa0b7c2c30e882"
SOURCE_TREE = "4bfc51d75c9e01e585db4cc073f952043ea01393"
CONTENT_DIGEST = (
    "sha256:4e5920ddd604d7905647af94eb460f7ab20124fb96ffdea73f50ed6efd5a4581"
)
SKILL_DIGEST = (
    "sha256:ca01a6b791a2638ab0bf1c85df9b6cf6f1f8c0851975cf4a3c896fc44121dae8"
)
PROFILE_ID = "toolchain-profile:java-engineering-standard:darwin-arm64:v1"
PROFILE_DIGEST = "sha256:c852142343ea97aef6d3a555e5500ecb633baf1a23d846d7bbe72a8bcf5e4490"
REGISTRATION_FINGERPRINT = (
    "sha256:cd5bbf5e763b38c96fccbf4c5a9357497c82e10fbf2272e4693fbcd2f63a708b"
)
LOCK_FINGERPRINT = (
    "sha256:90cf64c1425e75240e1225bea8e1d1f574420d06ee7bff9955e794ea6c20fb73"
)
TOOLCHAIN_PROFILE = {
    "profileId": PROFILE_ID,
    "profileDigest": PROFILE_DIGEST,
}


def test_neutral_java_registration_fixture_binds_exact_immutable_identity():
    root = Path(__file__).parents[1]
    fixture = root / "examples/java-engineering-standard-registration-fixture"
    lock = yaml.safe_load(
        (fixture / ".agent-evolution/capabilities.lock.yaml").read_text(
            encoding="utf-8"
        )
    )

    SchemaStore(root).validate("core/schemas/capability-lock.schema.json", lock)
    assert lock["project"] == "java-engineering-standard-registration-fixture"
    assert len(lock["capabilities"]) == 1
    capability = lock["capabilities"][0]
    assert capability["capabilityId"] == CAPABILITY_ID
    assert capability["sourceRegistrationId"] == REGISTRATION_ID
    assert capability["sourceCommit"] == SOURCE_COMMIT
    assert capability["sourceTree"] == SOURCE_TREE
    assert capability["resolvedContentDigest"] == CONTENT_DIGEST
    assert capability["validatorIdentity"]["environmentContract"] == (
        "MANAGED_TOOLCHAIN_PROFILE"
    )
    assert capability["validatorIdentity"]["toolchainProfile"] == TOOLCHAIN_PROFILE
    assert "toolchain" not in capability["validatorIdentity"]
    assert capability["validatorIdentity"]["gitHistoryContract"] == (
        "CANDIDATE_PARENT_TREE"
    )
    assert capability["validatorIdentity"]["timeoutSeconds"] == 600
    assert capability["registrationFingerprint"] == REGISTRATION_FINGERPRINT
    assert lock["lockFingerprint"] == LOCK_FINGERPRINT


@pytest.mark.parametrize("runtime", ["chatgpt", "codex"])
def test_projected_java_skill_is_self_contained_and_byte_identical_to_fixed_blob(
    runtime: str,
):
    root = Path(__file__).parents[1]
    pack = (
        root
        / f"generated/projections/{runtime}/java-engineering-standard-registration-fixture"
    )
    manifest = json.loads(
        (pack / "projection-manifest.json").read_text(encoding="utf-8")
    )
    SchemaStore(root).validate(
        "core/schemas/runtime-projection-manifest.schema.json", manifest
    )
    skill = pack / "skills/java-engineering-standard/SKILL.md"
    skill_bytes = skill.read_bytes()
    source_bytes = subprocess.run(
        [
            "git",
            "-C",
            "/Users/yuzhuangzhuang/Projects/java-engineering-standard",
            "show",
            f"{SOURCE_COMMIT}:skills/java-engineering-standard/SKILL.md",
        ],
        check=True,
        capture_output=True,
    ).stdout
    assert skill_bytes == source_bytes
    assert "sha256:" + hashlib.sha256(skill_bytes).hexdigest() == SKILL_DIGEST
    assert len(manifest["sourceCapabilities"]) == 1
    assert manifest["sourceCapabilities"][0]["kind"] == "FRAMEWORK"
    assert manifest["capabilityLockFingerprint"] == LOCK_FINGERPRINT
    source_capability = manifest["sourceCapabilities"][0]
    assert source_capability["registrationFingerprint"] == REGISTRATION_FINGERPRINT
    assert source_capability["validatorIdentity"]["toolchainProfile"] == (
        TOOLCHAIN_PROFILE
    )
    assert "toolchain" not in source_capability["validatorIdentity"]
    assert manifest["generatedSkills"][0]["skillBlobSha256"] == SKILL_DIGEST
    generated_skill = manifest["generatedSkills"][0]
    assert generated_skill["registrationFingerprint"] == REGISTRATION_FINGERPRINT
    assert generated_skill["validatorIdentity"]["toolchainProfile"] == (
        TOOLCHAIN_PROFILE
    )
    assert "toolchain" not in generated_skill["validatorIdentity"]
    assert generated_skill["projectionContract"] == "SELF_CONTAINED_SKILL_BUNDLE"
    assert len(generated_skill["resourceFiles"]) == 45
    assert len({item["sourcePath"] for item in generated_skill["resourceFiles"]}) == 45
    for resource in generated_skill["resourceFiles"]:
        target_bytes = (pack / resource["path"]).read_bytes()
        source_bytes = subprocess.run(
            [
                "git",
                "-C",
                "/Users/yuzhuangzhuang/Projects/java-engineering-standard",
                "show",
                f"{SOURCE_COMMIT}:{resource['sourcePath']}",
            ],
            check=True,
            capture_output=True,
        ).stdout
        assert target_bytes == source_bytes
        assert hashlib.sha256(target_bytes).hexdigest() == resource["sha256"]
    assert b"../" not in skill_bytes


@pytest.mark.parametrize("runtime", ["chatgpt", "codex"])
def test_projected_java_skill_install_plan_is_complete(tmp_path: Path, runtime: str):
    root = Path(__file__).parents[1]
    pack = (
        root
        / f"generated/projections/{runtime}/java-engineering-standard-registration-fixture"
    )
    target = tmp_path / "neutral-target"
    target.mkdir()
    plan = install_projection(root, pack, target)
    assert plan["gate"] == "PASS"
    assert len(plan["actions"]) == 45
