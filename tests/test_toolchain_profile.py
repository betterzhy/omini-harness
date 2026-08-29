from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from evolution_harness.hashing import canonical_json_bytes, sha256_bytes
from evolution_harness.schema import SchemaStore, SchemaValidationError


ROOT = Path(__file__).parents[1]
REGISTRY_SCHEMA = "core/schemas/capability-validator-toolchain-registry.schema.json"
BINDING_SCHEMA = "core/schemas/capability-validator-toolchain-binding.schema.json"
REGISTRATION_SCHEMA = "core/schemas/capability-pack-registration.schema.json"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def _profile_registry() -> dict[str, Any]:
    return {
        "schemaVersion": "capability-validator-toolchain-registry/v1",
        "artifacts": [
            {
                "artifactId": "artifact:ripgrep:15.2.0:darwin-arm64",
                "kind": "OFFICIAL_RELEASE_ARCHIVE",
                "platform": {"os": "darwin", "architecture": "arm64"},
                "sourceUri": "https://github.com/BurntSushi/ripgrep/releases/download/15.2.0/ripgrep-15.2.0-aarch64-apple-darwin.tar.gz",
                "archiveFormat": "TAR_GZ",
                "archiveSha256": DIGEST_B,
                "extractedRoot": "ripgrep-15.2.0-aarch64-apple-darwin",
            }
        ],
        "profiles": [
            {
                "schemaVersion": "capability-validator-toolchain-profile/v1",
                "profileId": "toolchain-profile:test:darwin-arm64:v1",
                "environmentAdapter": "JAVA_MAVEN_OFFLINE_V1",
                "platform": {"os": "darwin", "architecture": "arm64"},
                "commands": {
                    name: {
                        "artifactId": f"artifact:{name}:fixture",
                        "fileName": name,
                        "sha256": DIGEST_A,
                        "bindingPolicy": "HOST_ATTESTED",
                    }
                    for name in ("ruby", "rg", "java", "javac", "mvn")
                },
                "directories": {
                    name: {
                        "artifactId": f"artifact:{name}:fixture",
                        "sha256": DIGEST_A,
                        "bindingPolicy": "HOST_ATTESTED",
                    }
                    for name in ("javaHome", "mavenHome", "mavenRepository")
                },
                "relationships": {
                    "javaHomeCommands": ["java", "javac"],
                    "mavenHomeCommand": "mvn",
                    "mavenRepositoryLayout": "DOT_M2_REPOSITORY",
                },
            }
        ],
    }


def _host_binding() -> dict[str, Any]:
    return {
        "schemaVersion": "capability-validator-toolchain-binding/v1",
        "profileId": "toolchain-profile:test:darwin-arm64:v1",
        "commands": {
            "ruby": "/opt/toolchain/bin/ruby",
            "rg": "/opt/toolchain/bin/rg",
            "java": "/opt/toolchain/java/bin/java",
            "javac": "/opt/toolchain/java/bin/javac",
            "mvn": "/opt/toolchain/maven/bin/mvn",
        },
        "directories": {
            "javaHome": "/opt/toolchain/java",
            "mavenHome": "/opt/toolchain/maven",
            "mavenRepository": "/opt/toolchain/home/.m2/repository",
        },
    }


def _registration() -> dict[str, Any]:
    toolchain = {
        name: {"absolutePath": f"/opt/toolchain/bin/{name}", "sha256": DIGEST_A}
        for name in ("ruby", "rg", "java", "javac", "mvn")
    }
    toolchain.update(
        {
            name: {"absolutePath": f"/opt/toolchain/{name}", "sha256": DIGEST_A}
            for name in ("javaHome", "mavenHome", "mavenRepository")
        }
    )
    return {
        "schemaVersion": "capability-pack-registration/v1",
        "registrationId": "pack:test",
        "capabilityId": "framework:test:test",
        "packVersion": "1.0.0",
        "status": "ACTIVE",
        "distributionStatus": "LOCAL_ONLY",
        "source": {
            "kind": "LOCAL_GIT",
            "repositoryId": "test",
            "repositoryPath": "/tmp/test-pack",
            "commit": "1" * 40,
            "tree": "2" * 40,
        },
        "resolvedContentDigest": DIGEST_A,
        "validator": {
            "kind": "FIXED_CANDIDATE_GATE",
            "relativePath": "scripts/verify-capability-pack",
            "sha256": DIGEST_B,
            "argumentsContract": "CANDIDATE_COMMIT_TREE",
            "environmentContract": "REGISTERED_TOOLCHAIN_OFFLINE_CACHE",
            "toolchain": toolchain,
        },
    }


def _profile_registration() -> dict[str, Any]:
    registration = _registration()
    registration["validator"]["environmentContract"] = "MANAGED_TOOLCHAIN_PROFILE"
    del registration["validator"]["toolchain"]
    registration["validator"]["toolchainProfile"] = {
        "profileId": "toolchain-profile:test:darwin-arm64:v1",
        "profileDigest": DIGEST_A,
    }
    return registration


def test_toolchain_registry_schema_accepts_locator_free_profile():
    SchemaStore(ROOT).validate(REGISTRY_SCHEMA, _profile_registry())


@pytest.mark.parametrize(
    ("section", "name"),
    [("commands", "rg"), ("directories", "javaHome")],
)
def test_toolchain_profile_schema_rejects_host_locator(section: str, name: str):
    registry = _profile_registry()
    registry["profiles"][0][section][name]["absolutePath"] = "/Applications/ChatGPT.app/Contents/Resources/rg"

    with pytest.raises(SchemaValidationError, match="absolutePath"):
        SchemaStore(ROOT).validate(REGISTRY_SCHEMA, registry)


def test_toolchain_profile_directory_requires_binding_policy():
    registry = _profile_registry()
    del registry["profiles"][0]["directories"]["javaHome"]["bindingPolicy"]

    with pytest.raises(SchemaValidationError, match="bindingPolicy"):
        SchemaStore(ROOT).validate(REGISTRY_SCHEMA, registry)


@pytest.mark.parametrize("section", ["commands", "directories"])
def test_toolchain_profile_rejects_unsafe_logical_name(section: str):
    registry = _profile_registry()
    identity = registry["profiles"][0][section].pop(next(iter(registry["profiles"][0][section])))
    registry["profiles"][0][section]["../host-path"] = identity

    with pytest.raises(SchemaValidationError, match="host-path"):
        SchemaStore(ROOT).validate(REGISTRY_SCHEMA, registry)


def test_managed_store_command_requires_artifact_digest():
    registry = _profile_registry()
    registry["profiles"][0]["commands"]["rg"]["bindingPolicy"] = "HARNESS_MANAGED_STORE"

    with pytest.raises(SchemaValidationError, match="artifactDigest"):
        SchemaStore(ROOT).validate(REGISTRY_SCHEMA, registry)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda profile: profile["commands"].pop("ruby"),
        lambda profile: profile["commands"].update(
            {
                "python": {
                    "artifactId": "artifact:python:fixture",
                    "fileName": "python",
                    "sha256": DIGEST_A,
                    "bindingPolicy": "HOST_ATTESTED",
                }
            }
        ),
        lambda profile: profile["directories"].pop("mavenRepository"),
    ],
)
def test_java_maven_profile_requires_exact_logical_identities(mutation):
    registry = _profile_registry()
    mutation(registry["profiles"][0])

    with pytest.raises(SchemaValidationError):
        SchemaStore(ROOT).validate(REGISTRY_SCHEMA, registry)


def test_toolchain_binding_schema_accepts_absolute_host_locators():
    SchemaStore(ROOT).validate(BINDING_SCHEMA, _host_binding())


def test_toolchain_binding_schema_rejects_relative_host_locator():
    binding = _host_binding()
    binding["commands"]["rg"] = "bin/rg"

    with pytest.raises(SchemaValidationError, match="bin/rg"):
        SchemaStore(ROOT).validate(BINDING_SCHEMA, binding)


def test_toolchain_artifact_registry_is_valid_and_exact():
    registry = yaml.safe_load(
        (ROOT / "core/registries/capability-validator-toolchains.yaml").read_text(
            encoding="utf-8"
        )
    )
    SchemaStore(ROOT).validate(REGISTRY_SCHEMA, registry)

    assert registry["profiles"] == []
    assert registry["artifacts"] == [
        {
            "artifactId": "artifact:ripgrep:15.2.0:darwin-arm64",
            "kind": "OFFICIAL_RELEASE_ARCHIVE",
            "platform": {"os": "darwin", "architecture": "arm64"},
            "sourceUri": "https://github.com/BurntSushi/ripgrep/releases/download/15.2.0/ripgrep-15.2.0-aarch64-apple-darwin.tar.gz",
            "archiveFormat": "TAR_GZ",
            "archiveSha256": "sha256:3750b2e93f37e0c692657da574d7019a101c0084da05a790c83fd335bad973e4",
            "extractedRoot": "ripgrep-15.2.0-aarch64-apple-darwin",
            "extractedFiles": {
                "rg": "sha256:a326a1fb48074202e9ad41e4cd1e389eeea372c8c6f7d7e80da81176d5d9430e"
            },
            "provenancePolicy": "OFFICIAL_GITHUB_RELEASE_ARCHIVE_SHA256",
        }
    ]
    assert "sha256:" + sha256_bytes(canonical_json_bytes(registry["artifacts"][0])) == (
        "sha256:bfa2614eba25313624c604d16c6c727f3b243e5453b5b261321858f7eee75512"
    )


def test_legacy_registration_requires_toolchain():
    registration = _registration()
    del registration["validator"]["toolchain"]

    with pytest.raises(SchemaValidationError, match="toolchain"):
        SchemaStore(ROOT).validate(REGISTRATION_SCHEMA, registration)


def test_profile_registration_requires_toolchain_profile():
    registration = _profile_registration()
    del registration["validator"]["toolchainProfile"]

    with pytest.raises(SchemaValidationError, match="toolchainProfile"):
        SchemaStore(ROOT).validate(REGISTRATION_SCHEMA, registration)


def test_profile_registration_rejects_legacy_toolchain():
    registration = _profile_registration()
    registration["validator"]["toolchain"] = copy.deepcopy(_registration()["validator"]["toolchain"])

    with pytest.raises(SchemaValidationError, match="toolchain"):
        SchemaStore(ROOT).validate(REGISTRATION_SCHEMA, registration)


@pytest.mark.parametrize(
    "profile_digest",
    ["a" * 64, "sha256:" + "A" * 64, "sha256:" + "a" * 63],
)
def test_profile_registration_requires_canonical_sha256_digest(profile_digest: str):
    registration = _profile_registration()
    registration["validator"]["toolchainProfile"]["profileDigest"] = profile_digest

    with pytest.raises(SchemaValidationError, match="profileDigest"):
        SchemaStore(ROOT).validate(REGISTRATION_SCHEMA, registration)


def test_legacy_and_profile_registrations_are_both_valid():
    store = SchemaStore(ROOT)
    store.validate(REGISTRATION_SCHEMA, _registration())
    store.validate(REGISTRATION_SCHEMA, _profile_registration())
