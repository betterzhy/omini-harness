from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import yaml

from evolution_harness.schema import SchemaStore


CAPABILITY_ID = "framework:java:java-engineering-standard"
REGISTRATION_ID = "pack:java-engineering-standard"
SOURCE_COMMIT = "765e9d00a3173ecfe873c1646f5dbe375de677e7"
SOURCE_TREE = "d79644b05149419feba8cdd7860b7dbbb48e4961"
CONTENT_DIGEST = (
    "sha256:b226ed62d3b3e3710fb0a3611762864524ea94e8c15fe00a3b2b7e40943de666"
)
SKILL_DIGEST = (
    "sha256:ca01a6b791a2638ab0bf1c85df9b6cf6f1f8c0851975cf4a3c896fc44121dae8"
)


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
    assert capability["validatorIdentity"]["gitHistoryContract"] == (
        "CANDIDATE_PARENT_TREE"
    )


def test_projected_java_skill_is_self_contained_and_byte_identical_to_fixed_blob():
    root = Path(__file__).parents[1]
    pack = (
        root
        / "generated/projections/codex/java-engineering-standard-registration-fixture"
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
    assert manifest["generatedSkills"][0]["skillBlobSha256"] == SKILL_DIGEST
    assert b"../" not in skill_bytes
