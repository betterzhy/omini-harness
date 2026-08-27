from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml


EXTERNAL_CAPABILITY_ID = "workflow:web-high-fidelity:reference-driven-visual-fidelity"


def _copy_repo(tmp_path: Path) -> tuple[Path, Path]:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    for name in ["core", "design", "runtime", "examples"]:
        shutil.copytree(source / name, root / name)
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
    from evolution_harness.project import build_capability_lock, verify_capability_lock

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

    with pytest.raises(ValueError, match="external capability pack lock registration drift"):
        verify_capability_lock(root, project)


def test_external_pack_lock_rejects_validator_identity_drift(tmp_path: Path):
    from evolution_harness.project import build_capability_lock, verify_capability_lock

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

    with pytest.raises(ValueError, match="external capability pack lock registration drift"):
        verify_capability_lock(root, project)


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
