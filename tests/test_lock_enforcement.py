from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from capability_pack_test_support import retain_web_registration_fixture


EXTERNAL_CAPABILITY_ID = "workflow:web-high-fidelity:reference-driven-visual-fidelity"


def _schema_toolchain_identity() -> dict:
    commands = {
        name: {
            "absolutePath": f"/opt/toolchain/bin/{name}",
            "sha256": "sha256:" + "a" * 64,
        }
        for name in ("ruby", "rg", "java", "javac", "mvn")
    }
    commands.update(
        {
            name: {
                "absolutePath": f"/opt/toolchain/{name}",
                "sha256": "sha256:" + "b" * 64,
            }
            for name in ("javaHome", "mavenHome", "mavenRepository")
        }
    )
    return commands


def _schema_profile_identity() -> dict[str, str]:
    return {
        "profileId": "toolchain-profile:test:validator-coupling:v1",
        "profileDigest": "sha256:" + "c" * 64,
    }


def _minimal_v2_lock(validator_identity: dict) -> dict:
    digest = "d" * 64
    source_revision = "content-sha256:" + "e" * 64
    return {
        "schemaVersion": "capability-lock/v2",
        "project": "schema-fixture",
        "sourceHarnessRevision": source_revision,
        "disabledCapabilities": [],
        "capabilities": [
            {
                "capabilityId": "framework:test:validator-coupling",
                "resolvedVersion": "1.0.0",
                "contentHash": digest,
                "sourceHarnessRevision": source_revision,
                "resolvedBecause": ["schema-test"],
                "sourceKind": "EXTERNAL_CAPABILITY_PACK",
                "sourceRegistrationId": "pack:validator-coupling",
                "sourceCommit": "1" * 40,
                "sourceTree": "2" * 40,
                "resolvedContentDigest": "sha256:" + digest,
                "validatorIdentity": validator_identity,
                "registrationFingerprint": "sha256:" + "f" * 64,
            }
        ],
        "lockFingerprint": "sha256:" + "0" * 64,
    }


@pytest.mark.parametrize(
    ("case", "validator_fields", "valid"),
    [
        ("sanitized-empty", {"environmentContract": "SANITIZED"}, True),
        (
            "registered-toolchain",
            {
                "environmentContract": "REGISTERED_TOOLCHAIN_OFFLINE_CACHE",
                "toolchain": _schema_toolchain_identity(),
            },
            True,
        ),
        (
            "managed-profile",
            {
                "environmentContract": "MANAGED_TOOLCHAIN_PROFILE",
                "toolchainProfile": _schema_profile_identity(),
            },
            True,
        ),
        (
            "registered-missing-toolchain",
            {"environmentContract": "REGISTERED_TOOLCHAIN_OFFLINE_CACHE"},
            False,
        ),
        (
            "managed-missing-profile",
            {"environmentContract": "MANAGED_TOOLCHAIN_PROFILE"},
            False,
        ),
        (
            "managed-both-identities",
            {
                "environmentContract": "MANAGED_TOOLCHAIN_PROFILE",
                "toolchain": _schema_toolchain_identity(),
                "toolchainProfile": _schema_profile_identity(),
            },
            False,
        ),
        (
            "sanitized-profile",
            {
                "environmentContract": "SANITIZED",
                "toolchainProfile": _schema_profile_identity(),
            },
            False,
        ),
    ],
)
def test_capability_lock_validator_identity_enforces_environment_coupling(
    tmp_path: Path,
    case: str,
    validator_fields: dict,
    valid: bool,
):
    del case
    from evolution_harness.schema import SchemaStore, SchemaValidationError

    root = Path(__file__).parents[1]
    validator_identity = {
        "relativePath": "scripts/verify-capability-pack",
        "sha256": "sha256:" + "9" * 64,
        **validator_fields,
    }
    lock = _minimal_v2_lock(validator_identity)
    if valid:
        SchemaStore(root).validate("core/schemas/capability-lock.schema.json", lock)
        return
    with pytest.raises(SchemaValidationError):
        SchemaStore(root).validate("core/schemas/capability-lock.schema.json", lock)


def _copy_repo(tmp_path: Path) -> tuple[Path, Path]:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    for name in ["core", "design", "runtime", "examples"]:
        shutil.copytree(source / name, root / name)
    retain_web_registration_fixture(root)
    return root, root / "examples/project-fixture"


def _project_selecting_registered_pack(tmp_path: Path) -> tuple[Path, Path]:
    root, project = _copy_repo(tmp_path)
    binding_path = project / ".agent-evolution/capabilities.yaml"
    binding = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
    binding["capabilities"].append(EXTERNAL_CAPABILITY_ID)
    binding_path.write_text(yaml.safe_dump(binding, sort_keys=False), encoding="utf-8")
    return root, project


def _mutate_registration_digest(root: Path) -> None:
    path = root / "core/registries/capability-packs.yaml"
    registrations = yaml.safe_load(path.read_text(encoding="utf-8"))
    registrations[0]["resolvedContentDigest"] = "sha256:" + "f" * 64
    path.write_text(yaml.safe_dump(registrations, sort_keys=False), encoding="utf-8")


def _resign_v2_lock(lock: dict) -> None:
    from evolution_harness.project import (
        capability_lock_fingerprint,
        capability_lock_v2_source_revision,
    )

    source_revision = capability_lock_v2_source_revision(lock["capabilities"])
    lock["sourceHarnessRevision"] = source_revision
    for item in lock["capabilities"]:
        item["sourceHarnessRevision"] = source_revision
    lock["lockFingerprint"] = capability_lock_fingerprint(lock)


def _resolve(root: Path, project: Path):
    from evolution_harness.resolver import resolve_design_context

    return resolve_design_context(
        root,
        project,
        intent="architecture-review",
        topic="resolver-mvp",
        requested_output="review findings",
        runtime="CODEX",
    )


def _restore_file(path: Path, original: bytes) -> Callable[[], None]:
    return lambda: path.write_bytes(original)


def _mutate_lock_witness(
    root: Path, project: Path, witness: str
) -> Callable[[], None]:
    if witness == "lock":
        from evolution_harness.project import capability_lock_fingerprint

        path = project / ".agent-evolution/capabilities.lock.yaml"
        original = path.read_bytes()
        value = yaml.safe_load(original)
        value["capabilities"].reverse()
        value["lockFingerprint"] = capability_lock_fingerprint(value)
        path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        return _restore_file(path, original)
    if witness == "state":
        path = project / ".agent-evolution/design-state.yaml"
        original = path.read_bytes()
        value = yaml.safe_load(original)
        value["assumptions"].append("assumption://project-fixture/session-witness")
        path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        return _restore_file(path, original)
    if witness == "binding":
        path = project / ".agent-evolution/capabilities.yaml"
        original = path.read_bytes()
        value = yaml.safe_load(original)
        value["disabledCapabilities"].append(
            "skill:agent-design:architecture-review"
        )
        path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        return _restore_file(path, original)
    if witness == "profile-reasons":
        path = root / "runtime/profiles/agent-design-base.yaml"
        original = path.read_bytes()
        value = yaml.safe_load(original)
        value["capabilities"].append(EXTERNAL_CAPABILITY_ID)
        path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        return _restore_file(path, original)
    if witness in {"design-registry-input", "active-catalog-input"}:
        source = root / "design/capabilities/skills/architecture-review"
        target = root / "design/capabilities/skills" / witness
        shutil.copytree(source, target)
        asset_path = target / "asset.yaml"
        asset = yaml.safe_load(asset_path.read_text(encoding="utf-8"))
        asset["id"] = f"skill:agent-design:{witness}"
        asset["title"] = witness
        if witness == "design-registry-input":
            asset["lifecycle"] = "DEPRECATED"
        asset_path.write_text(
            yaml.safe_dump(asset, sort_keys=False), encoding="utf-8"
        )
        return lambda: shutil.rmtree(target)
    if witness == "internal-entry":
        path = root / "design/capabilities/skills/architecture-review/content.md"
        original = path.read_bytes()
        path.write_bytes(original + b"\nchanged during lock reuse\n")
        return _restore_file(path, original)
    if witness == "internal-external-collision":
        source = root / "design/capabilities/skills/architecture-review"
        target = root / "design/capabilities/skills/internal-external-collision"
        shutil.copytree(source, target)
        asset_path = target / "asset.yaml"
        asset = yaml.safe_load(asset_path.read_text(encoding="utf-8"))
        asset["id"] = EXTERNAL_CAPABILITY_ID
        asset["title"] = "Internal External Collision"
        asset_path.write_text(
            yaml.safe_dump(asset, sort_keys=False), encoding="utf-8"
        )
        return lambda: shutil.rmtree(target)
    raise AssertionError(f"unknown lock witness: {witness}")


def test_resolver_consumes_exact_lock_and_rejects_tampering(tmp_path: Path):
    root, project = _copy_repo(tmp_path)
    result = _resolve(root, project)
    assert result["capabilityLockFingerprint"].startswith("sha256:")

    lock_path = project / ".agent-evolution/capabilities.lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    lock["capabilities"][0]["contentHash"] = "0" * 64
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="capability lock"):
        _resolve(root, project)


def test_new_current_version_does_not_change_locked_selection(tmp_path: Path):
    root, project = _copy_repo(tmp_path)
    source = root / "design/capabilities/skills/architecture-review"
    target = root / "design/capabilities/skills/architecture-review-v2"
    shutil.copytree(source, target)
    asset_path = target / "asset.yaml"
    asset = yaml.safe_load(asset_path.read_text(encoding="utf-8"))
    asset["version"] = "1.1.0"
    asset_path.write_text(yaml.safe_dump(asset, sort_keys=False), encoding="utf-8")
    (target / "content.md").write_text("new current guidance\n", encoding="utf-8")

    result = _resolve(root, project)
    selected = {item["id"]: item for item in result["selectedCapabilities"]}
    assert selected["skill:agent-design:architecture-review"]["version"] == "1.0.0"


def test_binding_change_makes_existing_lock_stale(tmp_path: Path):
    root, project = _copy_repo(tmp_path)
    binding_path = project / ".agent-evolution/capabilities.yaml"
    binding = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
    binding["disabledCapabilities"].append("skill:agent-design:architecture-review")
    binding_path.write_text(yaml.safe_dump(binding, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="binding"):
        _resolve(root, project)


def test_projection_and_freshness_bind_lock_fingerprint(tmp_path: Path):
    from evolution_harness.projection import build_projection_pack, check_projection_freshness

    root, project = _copy_repo(tmp_path)
    resolved = _resolve(root, project)
    manifest = build_projection_pack(root, project, resolved, runtime="CODEX")
    assert manifest["capabilityLockFingerprint"] == resolved["capabilityLockFingerprint"]
    assert check_projection_freshness(root, project, runtime="CODEX").fresh

    lock_path = project / ".agent-evolution/capabilities.lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    lock["sourceHarnessRevision"] = "content-sha256:" + "f" * 64
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")
    freshness = check_projection_freshness(root, project, runtime="CODEX")
    assert not freshness.fresh
    assert freshness.reasons == ("projection-integrity-drift",)


def test_lock_rejects_inconsistent_entry_source_revision(tmp_path: Path):
    from evolution_harness.project import capability_lock_fingerprint, verify_capability_lock

    root, project = _copy_repo(tmp_path)
    lock_path = project / ".agent-evolution/capabilities.lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    lock["capabilities"][0]["sourceHarnessRevision"] = "content-sha256:" + "f" * 64
    lock["lockFingerprint"] = capability_lock_fingerprint(lock)
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="source revision mismatch"):
        verify_capability_lock(root, project)


def test_lock_rejects_self_consistent_but_forged_source_revision(tmp_path: Path):
    from evolution_harness.project import capability_lock_fingerprint, verify_capability_lock

    root, project = _copy_repo(tmp_path)
    lock_path = project / ".agent-evolution/capabilities.lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    forged = "content-sha256:" + "f" * 64
    lock["sourceHarnessRevision"] = forged
    for item in lock["capabilities"]:
        item["sourceHarnessRevision"] = forged
    lock["lockFingerprint"] = capability_lock_fingerprint(lock)
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="not reproducible"):
        verify_capability_lock(root, project)


def test_external_pack_lock_rejects_registry_digest_or_revision_drift(tmp_path: Path):
    from evolution_harness.project import build_capability_lock, verify_capability_lock

    root, project = _project_selecting_registered_pack(tmp_path)
    build_capability_lock(root, project, write=True)
    _mutate_registration_digest(root)

    with pytest.raises(ValueError, match="external capability pack lock registration drift"):
        verify_capability_lock(root, project)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sourceCommit", "a" * 40),
        ("sourceTree", "b" * 40),
        ("resolvedContentDigest", "sha256:" + "c" * 64),
        ("registrationFingerprint", "sha256:" + "d" * 64),
    ],
)
def test_external_pack_lock_rejects_copied_registration_identity_drift(
    tmp_path: Path, field: str, value: str
):
    from evolution_harness.project import (
        _ExternalCapabilityLockRegistrationDrift,
        build_capability_lock,
        verify_capability_lock,
    )

    root, project = _project_selecting_registered_pack(tmp_path)
    build_capability_lock(root, project, write=True)
    lock_path = project / ".agent-evolution/capabilities.lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    external = next(
        item for item in lock["capabilities"] if item["capabilityId"] == EXTERNAL_CAPABILITY_ID
    )
    external[field] = value
    _resign_v2_lock(lock)
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")

    with pytest.raises(_ExternalCapabilityLockRegistrationDrift) as exc_info:
        verify_capability_lock(root, project)
    assert str(exc_info.value) == (
        f"external capability pack lock registration drift: {EXTERNAL_CAPABILITY_ID}"
    )


def test_external_pack_lock_rejects_validator_identity_drift(tmp_path: Path):
    from evolution_harness.project import (
        _ExternalCapabilityLockRegistrationDrift,
        build_capability_lock,
        verify_capability_lock,
    )

    root, project = _project_selecting_registered_pack(tmp_path)
    build_capability_lock(root, project, write=True)
    lock_path = project / ".agent-evolution/capabilities.lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    external = next(
        item for item in lock["capabilities"] if item["capabilityId"] == EXTERNAL_CAPABILITY_ID
    )
    external["validatorIdentity"]["sha256"] = "sha256:" + "e" * 64
    _resign_v2_lock(lock)
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")

    with pytest.raises(_ExternalCapabilityLockRegistrationDrift) as exc_info:
        verify_capability_lock(root, project)
    assert str(exc_info.value) == (
        f"external capability pack lock registration drift: {EXTERNAL_CAPABILITY_ID}"
    )


@pytest.mark.parametrize(
    "failure_message",
    [
        "capability pack candidate Gate failed",
        "capability pack validator toolchain identity mismatch",
        "capability pack source commit does not match checkout HEAD",
    ],
)
def test_external_pack_verification_failure_is_not_registration_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_message: str,
):
    import evolution_harness.project as project_module
    from evolution_harness.project import (
        _ExternalCapabilityLockRegistrationDrift,
        build_capability_lock,
        verify_capability_lock,
    )

    root, project = _project_selecting_registered_pack(tmp_path)
    build_capability_lock(root, project, write=True)
    original_failure = ValueError(failure_message)

    def fail_pack_verification(*args, **kwargs):
        del args, kwargs
        raise original_failure

    monkeypatch.setattr(
        project_module,
        "_get_verified_capability_pack",
        fail_pack_verification,
    )

    with pytest.raises(ValueError) as exc_info:
        verify_capability_lock(root, project)
    assert str(exc_info.value) == (
        f"external capability pack lock registration drift: {EXTERNAL_CAPABILITY_ID}"
    )
    assert type(exc_info.value) is ValueError
    assert not isinstance(
        exc_info.value,
        _ExternalCapabilityLockRegistrationDrift,
    )
    assert exc_info.value.__cause__ is original_failure


def test_external_pack_lock_rejects_changed_resolved_reasons(tmp_path: Path):
    from evolution_harness.project import (
        build_capability_lock,
        capability_lock_fingerprint,
        verify_capability_lock,
    )

    root, project = _project_selecting_registered_pack(tmp_path)
    build_capability_lock(root, project, write=True)
    lock_path = project / ".agent-evolution/capabilities.lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    external = next(
        item for item in lock["capabilities"] if item["capabilityId"] == EXTERNAL_CAPABILITY_ID
    )
    external["resolvedBecause"] = ["project-extension"]
    lock["lockFingerprint"] = capability_lock_fingerprint(lock)
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="binding reasons drift"):
        verify_capability_lock(root, project)


def test_external_pack_lock_rejects_duplicate_capability_ids(tmp_path: Path):
    from evolution_harness.project import build_capability_lock, verify_capability_lock

    root, project = _project_selecting_registered_pack(tmp_path)
    build_capability_lock(root, project, write=True)
    lock_path = project / ".agent-evolution/capabilities.lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    external = next(
        item for item in lock["capabilities"] if item["capabilityId"] == EXTERNAL_CAPABILITY_ID
    )
    lock["capabilities"].append(yaml.safe_load(yaml.safe_dump(external)))
    _resign_v2_lock(lock)
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate capability ids"):
        verify_capability_lock(root, project)


def test_v1_lock_never_reinterprets_external_source_fields(tmp_path: Path):
    from evolution_harness.project import capability_lock_fingerprint, verify_capability_lock
    from evolution_harness.schema import SchemaValidationError

    root, project = _copy_repo(tmp_path)
    lock_path = project / ".agent-evolution/capabilities.lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    lock["capabilities"][0]["sourceKind"] = "EXTERNAL_CAPABILITY_PACK"
    lock["lockFingerprint"] = capability_lock_fingerprint(lock)
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")

    with pytest.raises(SchemaValidationError):
        verify_capability_lock(root, project)


def test_internal_only_v2_lock_is_rejected_even_when_self_consistent(tmp_path: Path):
    from evolution_harness.project import (
        build_capability_lock,
        verify_capability_lock,
    )
    from evolution_harness.schema import SchemaValidationError

    root, project = _copy_repo(tmp_path)
    lock_path = project / ".agent-evolution/capabilities.lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    lock["schemaVersion"] = "capability-lock/v2"
    for item in lock["capabilities"]:
        item["sourceKind"] = "HARNESS_CANONICAL"
    _resign_v2_lock(lock)
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")

    with pytest.raises(SchemaValidationError):
        verify_capability_lock(root, project)

    assert build_capability_lock(root, project, write=False)["schemaVersion"] == (
        "capability-lock/v1"
    )


def test_verification_session_reuses_exact_lock_after_rechecking_all_witnesses(
    tmp_path: Path,
):
    from evolution_harness.capability_pack_registry import CapabilityVerificationSession
    from evolution_harness.project import (
        build_capability_lock,
        verify_capability_lock,
        verify_capability_lock_context,
    )

    root, project = _project_selecting_registered_pack(tmp_path)
    with CapabilityVerificationSession(
        root,
        allowed_capability_ids={EXTERNAL_CAPABILITY_ID},
    ) as session:
        build_capability_lock(
            root,
            project,
            write=True,
            verification_session=session,
        )
        context = verify_capability_lock_context(
            root,
            project,
            verification_session=session,
        )
        first_lock, first_entries = context.public_result()
        first_lock["project"] = "caller-mutation"
        first_entries[EXTERNAL_CAPABILITY_ID]["status"] = "caller-mutation"

        second_lock, second_entries = verify_capability_lock(
            root,
            project,
            verification_session=session,
        )
        snapshot = session.stats

    assert second_lock["project"] == "project-fixture"
    assert second_entries[EXTERNAL_CAPABILITY_ID]["status"] == "ACTIVE"
    assert snapshot.full_candidate_gate_count == 1
    assert snapshot.verified_lock_count == 1
    assert snapshot.lock_reuse_hit_count == 1
    assert snapshot.lock_witness_recheck_count == 2
    assert snapshot.active_use_lease_count == 0


def test_external_lock_source_preserves_plain_toolchain_compatibility_fields(
    tmp_path: Path,
):
    from types import MappingProxyType

    from evolution_harness.hashing import canonical_json_bytes
    from evolution_harness.project import _external_lock_source

    root, _ = _copy_repo(tmp_path)
    registrations = yaml.safe_load(
        (root / "core/registries/capability-packs.yaml").read_text(encoding="utf-8")
    )
    registration = registrations[0]
    registration["validator"]["toolchain"] = {
        "javaHome": {"absolutePath": "/opt/java", "sha256": "sha256:" + "a" * 64}
    }

    def readonly(value):
        if isinstance(value, dict):
            return MappingProxyType(
                {key: readonly(item) for key, item in value.items()}
            )
        if isinstance(value, list):
            return tuple(readonly(item) for item in value)
        return value

    source = _external_lock_source(readonly(registration))

    assert isinstance(source["validatorIdentity"]["toolchain"], dict)
    assert canonical_json_bytes(source)


def test_external_lock_source_copies_only_canonical_profile_identity(
    tmp_path: Path,
):
    from types import MappingProxyType

    from evolution_harness.hashing import canonical_json_bytes
    from evolution_harness.project import _external_lock_source

    root, _ = _copy_repo(tmp_path)
    registrations = yaml.safe_load(
        (root / "core/registries/capability-packs.yaml").read_text(encoding="utf-8")
    )
    registration = registrations[0]
    registration["validator"]["environmentContract"] = "MANAGED_TOOLCHAIN_PROFILE"
    registration["validator"]["toolchainProfile"] = {
        "profileId": "toolchain-profile:test:canonical-relocation:v1",
        "profileDigest": "sha256:" + "a" * 64,
    }

    def readonly(value):
        if isinstance(value, dict):
            return MappingProxyType(
                {key: readonly(item) for key, item in value.items()}
            )
        if isinstance(value, list):
            return tuple(readonly(item) for item in value)
        return value

    source = _external_lock_source(readonly(registration))

    assert source["validatorIdentity"]["toolchainProfile"] == {
        "profileId": "toolchain-profile:test:canonical-relocation:v1",
        "profileDigest": "sha256:" + "a" * 64,
    }
    serialized = canonical_json_bytes(source)
    assert b"absolutePath" not in serialized
    assert b"binding" not in serialized
    assert b"witness" not in serialized
    assert b"ChatGPT.app" not in serialized


@pytest.mark.parametrize(
    "witness",
    [
        "lock",
        "state",
        "binding",
        "profile-reasons",
        "design-registry-input",
        "active-catalog-input",
        "internal-entry",
        "internal-external-collision",
    ],
)
def test_verification_session_rejects_every_changed_lock_witness_and_stays_poisoned(
    tmp_path: Path,
    witness: str,
):
    from evolution_harness.capability_pack_registry import CapabilityVerificationSession
    from evolution_harness.project import build_capability_lock, verify_capability_lock

    root, project = _project_selecting_registered_pack(tmp_path)
    with CapabilityVerificationSession(
        root,
        allowed_capability_ids={EXTERNAL_CAPABILITY_ID},
    ) as session:
        build_capability_lock(
            root,
            project,
            write=True,
            verification_session=session,
        )
        first_lock, first_entries = verify_capability_lock(
            root,
            project,
            verification_session=session,
        )
        restore = _mutate_lock_witness(root, project, witness)
        try:
            with pytest.raises(ValueError):
                verify_capability_lock(
                    root,
                    project,
                    verification_session=session,
                )
        finally:
            restore()

        with pytest.raises(ValueError, match="failed"):
            verify_capability_lock(
                root,
                project,
                verification_session=session,
            )

    assert first_lock["lockFingerprint"]
    assert EXTERNAL_CAPABILITY_ID in first_entries


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("invalid-schema", "schema validation failed"),
        ("invalid-fingerprint", "fingerprint mismatch"),
        ("changed-external-ids", "not allowed by verification session"),
    ],
)
def test_verification_session_prelease_lock_failure_stays_poisoned_after_restore(
    tmp_path: Path,
    failure: str,
    message: str,
):
    from evolution_harness.capability_pack_registry import CapabilityVerificationSession
    from evolution_harness.project import build_capability_lock, verify_capability_lock
    from evolution_harness.schema import SchemaValidationError

    root, project = _project_selecting_registered_pack(tmp_path)
    lock_path = project / ".agent-evolution/capabilities.lock.yaml"
    with CapabilityVerificationSession(
        root,
        allowed_capability_ids={EXTERNAL_CAPABILITY_ID},
    ) as session:
        build_capability_lock(
            root,
            project,
            write=True,
            verification_session=session,
        )
        first_lock, first_entries = verify_capability_lock(
            root,
            project,
            verification_session=session,
        )
        original = lock_path.read_bytes()
        changed = yaml.safe_load(original)
        if failure == "invalid-schema":
            del changed["project"]
        elif failure == "invalid-fingerprint":
            changed["lockFingerprint"] = "sha256:" + "f" * 64
        else:
            external = next(
                item
                for item in changed["capabilities"]
                if item["capabilityId"] == EXTERNAL_CAPABILITY_ID
            )
            external["capabilityId"] = (
                "workflow:web-high-fidelity:unallowed-session-capability"
            )
            _resign_v2_lock(changed)
        lock_path.write_text(
            yaml.safe_dump(changed, sort_keys=False), encoding="utf-8"
        )
        try:
            with pytest.raises(ValueError, match=message) as caught:
                verify_capability_lock(
                    root,
                    project,
                    verification_session=session,
                )
            if failure == "invalid-schema":
                assert type(caught.value) is SchemaValidationError
            else:
                assert type(caught.value) is ValueError
        finally:
            lock_path.write_bytes(original)

        with pytest.raises(ValueError, match="failed"):
            verify_capability_lock(
                root,
                project,
                verification_session=session,
            )
        snapshot = session.stats

    assert first_lock["lockFingerprint"]
    assert EXTERNAL_CAPABILITY_ID in first_entries
    assert snapshot.full_candidate_gate_count == 1
    assert snapshot.active_use_lease_count == 0
