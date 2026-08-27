from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
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


def _resolved(root: Path, project: Path, *, runtime: str):
    from evolution_harness.resolver import resolve_design_context
    return resolve_design_context(
        root, project, intent="architecture-review", topic="resolver-mvp",
        requested_output="review findings", runtime=runtime
    )


def _external_pack_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    from evolution_harness.project import build_capability_lock

    root, project = _copy_repo(tmp_path)
    registry_path = root / "core/registries/capability-packs.yaml"
    registrations = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    source = tmp_path / "external-pack"
    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "--no-hardlinks",
            registrations[0]["source"]["repositoryPath"],
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    registrations[0]["source"]["repositoryPath"] = str(source)
    registry_path.write_text(
        yaml.safe_dump(registrations, sort_keys=False), encoding="utf-8"
    )
    schema_path = root / "core/schemas/capability-pack-registration.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["properties"]["source"]["properties"]["repositoryPath"]["const"] = str(
        source
    )
    schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    binding_path = project / ".agent-evolution/capabilities.yaml"
    binding = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
    binding["capabilities"].append(EXTERNAL_CAPABILITY_ID)
    binding_path.write_text(yaml.safe_dump(binding, sort_keys=False), encoding="utf-8")
    build_capability_lock(root, project, write=True)
    return root, project, source


def _git_bytes(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
    ).stdout


def _commit_and_relock(root: Path, project: Path, source: Path, message: str) -> None:
    from evolution_harness.capability_pack_registry import (
        compute_capability_pack_content_digest,
    )
    from evolution_harness.project import build_capability_lock

    subprocess.run(
        ["git", "-C", str(source), "config", "user.name", "Projection Test"],
        check=True,
    )
    validator = source / "scripts/verify-capability-pack"
    validator.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "[ \"$#\" -eq 2 ]\n"
        "[ \"$(git -C \"${0%/*}/..\" rev-parse HEAD)\" = \"$1\" ]\n"
        "[ \"$(git -C \"${0%/*}/..\" rev-parse 'HEAD^{tree}')\" = \"$2\" ]\n"
        "[ -z \"$(git -C \"${0%/*}/..\" status --porcelain=v1 --untracked-files=all)\" ]\n",
        encoding="utf-8",
    )
    validator.chmod(0o755)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "config",
            "user.email",
            "projection-test@example.invalid",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "add", "-A"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(source), "commit", "-qm", message],
        check=True,
        capture_output=True,
    )
    registry_path = root / "core/registries/capability-packs.yaml"
    registrations = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registrations[0]["source"]["commit"] = _git_bytes(
        source, "rev-parse", "HEAD"
    ).decode("ascii").strip()
    registrations[0]["source"]["tree"] = _git_bytes(
        source, "rev-parse", "HEAD^{tree}"
    ).decode("ascii").strip()
    pack_manifest = yaml.safe_load(
        (source / "capability-pack.yaml").read_text(encoding="utf-8")
    )
    registrations[0]["resolvedContentDigest"] = compute_capability_pack_content_digest(
        source, pack_manifest
    )
    registrations[0]["validator"]["sha256"] = (
        "sha256:" + hashlib.sha256(validator.read_bytes()).hexdigest()
    )
    registry_path.write_text(
        yaml.safe_dump(registrations, sort_keys=False), encoding="utf-8"
    )
    build_capability_lock(root, project, write=True)


def _advance_external_pack_identity(root: Path, project: Path, source: Path) -> None:
    skill_path = source / "skills/web-high-fidelity/SKILL.md"
    skill_path.write_text(
        skill_path.read_text(encoding="utf-8")
        + "\n<!-- projection source identity advanced -->\n",
        encoding="utf-8",
    )
    _commit_and_relock(root, project, source, "test: advance projection source")


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_projection_snapshots_external_skill_from_locked_git_blob(tmp_path: Path):
    from evolution_harness.projection import build_projection_pack

    root, project, source = _external_pack_project(tmp_path)
    resolved = _resolved(root, project, runtime="CODEX")

    manifest = build_projection_pack(root, project, resolved, runtime="CODEX")

    skill = root / "generated/projections/codex/project-fixture/skills/web-high-fidelity/SKILL.md"
    registration = yaml.safe_load(
        (root / "core/registries/capability-packs.yaml").read_text(encoding="utf-8")
    )[0]
    locked_bytes = _git_bytes(
        source,
        "show",
        f"{registration['source']['commit']}:skills/web-high-fidelity/SKILL.md",
    )
    assert skill.read_bytes() == locked_bytes
    external_source = next(
        item
        for item in manifest["sourceCapabilities"]
        if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK"
    )
    assert external_source["id"] == EXTERNAL_CAPABILITY_ID
    assert manifest["generatedSkills"][-1]["skillBlobSha256"] == (
        "sha256:" + hashlib.sha256(locked_bytes).hexdigest()
    )
    pack = root / "generated/projections/codex/project-fixture"
    projected_paths = {
        path.relative_to(pack).as_posix() for path in pack.rglob("*") if path.is_file()
    }
    assert not any(path.startswith(("docs/", "templates/")) for path in projected_paths)
    assert [
        item
        for item in manifest["generatedSkills"]
        if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK"
    ] == [manifest["generatedSkills"][-1]]


def test_projection_build_rejects_external_identity_drift_after_blob_read_without_replacing_canonical(
    tmp_path: Path, monkeypatch
):
    from evolution_harness import projection

    root, project, source = _external_pack_project(tmp_path)
    resolved = _resolved(root, project, runtime="CODEX")
    projection.build_projection_pack(root, project, resolved, runtime="CODEX")
    pack = root / "generated/projections/codex/project-fixture"
    before = _file_snapshot(pack)
    original_read = projection.read_registered_pack_blob
    advanced = False

    def read_then_advance(registration, relative_path):
        nonlocal advanced
        data = original_read(registration, relative_path)
        if not advanced:
            advanced = True
            _advance_external_pack_identity(root, project, source)
        return data

    monkeypatch.setattr(projection, "read_registered_pack_blob", read_then_advance)

    with pytest.raises(projection.ProjectionError, match="external source identity drift"):
        projection.build_projection_pack(root, project, resolved, runtime="CODEX")

    assert advanced
    assert _file_snapshot(pack) == before
    assert not list(pack.parent.glob(".project-fixture.*"))


def test_projection_validation_rejects_external_identity_drift_after_blob_read(
    tmp_path: Path, monkeypatch
):
    from evolution_harness import projection

    root, project, source = _external_pack_project(tmp_path)
    resolved = _resolved(root, project, runtime="CODEX")
    projection.build_projection_pack(root, project, resolved, runtime="CODEX")
    pack = root / "generated/projections/codex/project-fixture"
    before = _file_snapshot(pack)
    original_read = projection.read_registered_pack_blob
    advanced = False

    def read_then_advance(registration, relative_path):
        nonlocal advanced
        data = original_read(registration, relative_path)
        if not advanced:
            advanced = True
            _advance_external_pack_identity(root, project, source)
        return data

    monkeypatch.setattr(projection, "read_registered_pack_blob", read_then_advance)

    with pytest.raises(projection.ProjectionError, match="external source identity drift"):
        projection.validate_projection_pack(root, project, pack, runtime="CODEX")

    assert advanced
    assert _file_snapshot(pack) == before


def test_registered_pack_blob_reader_rejects_unsafe_or_missing_paths(tmp_path: Path):
    from evolution_harness.capability_pack_registry import read_registered_pack_blob
    from evolution_harness.project import verify_capability_lock

    root, project, _ = _external_pack_project(tmp_path)
    _, verified = verify_capability_lock(root, project)
    registration = verified[EXTERNAL_CAPABILITY_ID]

    with pytest.raises(ValueError, match="path is unsafe"):
        read_registered_pack_blob(registration, "../SKILL.md")
    with pytest.raises(ValueError, match="tracked file is unavailable"):
        read_registered_pack_blob(registration, "skills/web-high-fidelity/MISSING.md")


def test_registered_pack_blob_reader_rejects_symlink_mode(tmp_path: Path):
    from evolution_harness.capability_pack_registry import read_registered_pack_blob
    from evolution_harness.hashing import canonical_json_bytes, sha256_bytes
    from evolution_harness.project import verify_capability_lock

    root, project, source = _external_pack_project(tmp_path)
    _, verified = verify_capability_lock(root, project)
    registration = verified[EXTERNAL_CAPABILITY_ID]
    skill_path = source / "skills/web-high-fidelity/SKILL.md"
    skill_path.unlink()
    skill_path.symlink_to("../../docs/01-OPERATING-MODEL.md")
    subprocess.run(
        ["git", "-C", str(source), "config", "user.name", "Projection Test"],
        check=True,
    )
    subprocess.run(
        [
            "git", "-C", str(source), "config", "user.email",
            "projection-test@example.invalid",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "add", "-A"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(source), "commit", "-qm", "test: symlink Skill"],
        check=True,
        capture_output=True,
    )
    registration["source"]["commit"] = _git_bytes(
        source, "rev-parse", "HEAD"
    ).decode("ascii").strip()
    registration["source"]["tree"] = _git_bytes(
        source, "rev-parse", "HEAD^{tree}"
    ).decode("ascii").strip()
    record = {
        key: value
        for key, value in registration.items()
        if key not in {"sourceKind", "registrationFingerprint", "manifest"}
    }
    registration["registrationFingerprint"] = (
        "sha256:" + sha256_bytes(canonical_json_bytes(record))
    )

    with pytest.raises(ValueError, match="active content contains symlink"):
        read_registered_pack_blob(
            registration, "skills/web-high-fidelity/SKILL.md"
        )


def test_projection_rejects_external_skill_front_matter_name_drift(tmp_path: Path):
    from evolution_harness.projection import ProjectionError, build_projection_pack

    root, project, source = _external_pack_project(tmp_path)
    skill_path = source / "skills/web-high-fidelity/SKILL.md"
    skill_path.write_text(
        skill_path.read_text(encoding="utf-8").replace(
            "name: web-high-fidelity", "name: renamed-skill", 1
        ),
        encoding="utf-8",
    )
    _commit_and_relock(root, project, source, "test: front matter drift")
    resolved = _resolved(root, project, runtime="CODEX")

    with pytest.raises(ProjectionError, match="front matter name drift"):
        build_projection_pack(root, project, resolved, runtime="CODEX")


def test_projection_rejects_external_manifest_skill_path_drift(tmp_path: Path):
    from evolution_harness.projection import ProjectionError, build_projection_pack

    root, project, source = _external_pack_project(tmp_path)
    manifest_path = source / "capability-pack.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["skillPath"] = "docs/01-OPERATING-MODEL.md"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    _commit_and_relock(root, project, source, "test: Skill path drift")
    resolved = _resolved(root, project, runtime="CODEX")

    with pytest.raises(ProjectionError, match="Skill declaration path drift"):
        build_projection_pack(root, project, resolved, runtime="CODEX")


def test_projection_rejects_registry_change_after_external_lock(tmp_path: Path):
    from evolution_harness.projection import build_projection_pack

    root, project, _ = _external_pack_project(tmp_path)
    resolved = _resolved(root, project, runtime="CODEX")
    registry_path = root / "core/registries/capability-packs.yaml"
    registrations = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registrations[0]["resolvedContentDigest"] = "sha256:" + "0" * 64
    registry_path.write_text(
        yaml.safe_dump(registrations, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="external capability pack lock registration drift"):
        build_projection_pack(root, project, resolved, runtime="CODEX")


@pytest.mark.parametrize(
    ("section", "field", "replacement"),
    [
        ("sourceCapabilities", "sourceCommit", "a" * 40),
        ("generatedSkills", "skillBlobSha256", "sha256:" + "b" * 64),
    ],
)
def test_projection_validation_rejects_external_manifest_provenance_drift(
    tmp_path: Path, section: str, field: str, replacement: str
):
    from evolution_harness.projection import (
        ProjectionError,
        build_projection_pack,
        validate_projection_pack,
    )

    root, project, _ = _external_pack_project(tmp_path)
    resolved = _resolved(root, project, runtime="CODEX")
    build_projection_pack(root, project, resolved, runtime="CODEX")
    pack = root / "generated/projections/codex/project-fixture"
    manifest_path = pack / "projection-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    external = next(
        item
        for item in manifest[section]
        if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK"
    )
    external[field] = replacement
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ProjectionError, match="source capability mismatch|generated skill mismatch"):
        validate_projection_pack(root, project, pack, runtime="CODEX")


def test_chatgpt_and_codex_projection_preserve_same_semantic_capability_identity(tmp_path: Path):
    from evolution_harness.projection import build_projection_pack

    root, project = _copy_repo(tmp_path)
    chat = build_projection_pack(root, project, _resolved(root, project, runtime="CHATGPT"), runtime="CHATGPT")
    codex = build_projection_pack(root, project, _resolved(root, project, runtime="CODEX"), runtime="CODEX")
    chat_sources = [(x["id"], x["version"], x["contentHash"]) for x in chat["sourceCapabilities"]]
    codex_sources = [(x["id"], x["version"], x["contentHash"]) for x in codex["sourceCapabilities"]]
    assert chat_sources == codex_sources
    assert chat["runtime"] == "CHATGPT" and codex["runtime"] == "CODEX"
    assert chat["projectionType"] != codex["projectionType"]


def test_generated_skill_traces_source_and_embeds_only_selected_referenced_guidance(tmp_path: Path):
    from evolution_harness.projection import AGENT_SKILL_PROJECTION_VERSION, build_projection_pack

    root, project = _copy_repo(tmp_path)
    manifest = build_projection_pack(root, project, _resolved(root, project, runtime="CHATGPT"), runtime="CHATGPT")
    pack = root / "generated/projections/chatgpt/project-fixture"
    skill_path = pack / "skills/architecture-review/SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    source = next(x for x in manifest["sourceCapabilities"] if x["id"] == "skill:agent-design:architecture-review")
    assert "skill:agent-design:architecture-review" in text
    assert source["version"] in text
    assert source["contentHash"] in text
    assert AGENT_SKILL_PROJECTION_VERSION in text
    assert "framework:agent-design:authority-analysis" in text
    assert "framework:agent-design:lifecycle-analysis" in text
    assert "principle:agent-design:project-truth-over-generic-guidance" in text
    assert "principle:agent-design:canonical-capability-not-runtime-prompt" not in text
    assert "principle:agent-design:closure-requires-authority" not in text


def test_projection_version_is_independent_from_canonical_semver(tmp_path: Path):
    from evolution_harness.projection import build_projection_pack

    root, project = _copy_repo(tmp_path)
    manifest = build_projection_pack(root, project, _resolved(root, project, runtime="CHATGPT"), runtime="CHATGPT")
    assert manifest["projectionVersion"].startswith("chatgpt-project-pack/")
    assert all(manifest["projectionVersion"] != item["version"] for item in manifest["sourceCapabilities"])
    assert all(item["skillProjectionVersion"] == "agent-skill-projection/1" for item in manifest["generatedSkills"])


def test_projection_visibility_gate_omits_private_referenced_content(tmp_path: Path):
    from evolution_harness.projection import build_projection_pack
    from evolution_harness.project import build_capability_lock

    root, project = _copy_repo(tmp_path)
    asset_path = root / "design/capabilities/frameworks/authority-analysis/asset.yaml"
    asset = yaml.safe_load(asset_path.read_text(encoding="utf-8"))
    asset["visibility"] = "PRIVATE"
    asset_path.write_text(yaml.safe_dump(asset, sort_keys=False), encoding="utf-8")
    content_path = root / "design/capabilities/frameworks/authority-analysis/content.md"
    content_path.write_text(content_path.read_text(encoding="utf-8") + "\nSECRET_PRIVATE_GUIDANCE\n", encoding="utf-8")
    build_capability_lock(root, project, write=True)
    resolved = _resolved(root, project, runtime="CHATGPT")
    manifest = build_projection_pack(root, project, resolved, runtime="CHATGPT")
    text = (root / "generated/projections/chatgpt/project-fixture/skills/architecture-review/SKILL.md").read_text(encoding="utf-8")
    assert "SECRET_PRIVATE_GUIDANCE" not in text
    assert any(item["id"] == "framework:agent-design:authority-analysis" and item["reason"] == "visibility-gate" for item in manifest["omittedReferences"])


def test_projection_freshness_detects_generated_edit_and_canonical_hash_change(tmp_path: Path):
    from evolution_harness.projection import build_projection_pack, check_projection_freshness

    root, project = _copy_repo(tmp_path)
    resolved = _resolved(root, project, runtime="CHATGPT")
    build_projection_pack(root, project, resolved, runtime="CHATGPT")
    assert check_projection_freshness(root, project, runtime="CHATGPT").fresh
    skill = root / "generated/projections/chatgpt/project-fixture/skills/architecture-review/SKILL.md"
    original = skill.read_text(encoding="utf-8")
    skill.write_text(original + "\nmanual edit\n", encoding="utf-8")
    check = check_projection_freshness(root, project, runtime="CHATGPT")
    assert not check.fresh and check.reasons == ("projection-integrity-drift",)
    build_projection_pack(root, project, resolved, runtime="CHATGPT")
    assert skill.read_text(encoding="utf-8") == original
    canonical = root / "design/capabilities/skills/architecture-review/content.md"
    canonical.write_text(canonical.read_text(encoding="utf-8") + "\ncanonical change without projection rebuild\n", encoding="utf-8")
    check = check_projection_freshness(root, project, runtime="CHATGPT")
    assert not check.fresh and check.reasons == ("projection-integrity-drift",)


def test_codex_pack_never_overwrites_or_generates_agents_md(tmp_path: Path):
    from evolution_harness.projection import build_projection_pack

    root, project = _copy_repo(tmp_path)
    agents = project / "AGENTS.md"
    agents.write_text("# Existing project guidance\n", encoding="utf-8")
    build_projection_pack(root, project, _resolved(root, project, runtime="CODEX"), runtime="CODEX")
    assert agents.read_text(encoding="utf-8") == "# Existing project guidance\n"
    pack = root / "generated/projections/codex/project-fixture"
    assert not list(pack.rglob("AGENTS.md"))
    assert (pack / "repository-guidance.md").exists()
    assert (pack / "resolved-task-context.md").exists()


def test_projection_manifest_file_hashes_match_generated_files(tmp_path: Path):
    from evolution_harness.hashing import file_sha256
    from evolution_harness.projection import build_projection_pack

    root, project = _copy_repo(tmp_path)
    manifest = build_projection_pack(root, project, _resolved(root, project, runtime="CHATGPT"), runtime="CHATGPT")
    pack = root / "generated/projections/chatgpt/project-fixture"
    stored = json.loads((pack / "projection-manifest.json").read_text(encoding="utf-8"))
    assert stored == manifest
    for item in manifest["generatedFiles"]:
        assert file_sha256(pack / item["path"]) == item["sha256"]


def test_projection_pack_preserves_machine_readable_resolved_context(tmp_path: Path):
    from evolution_harness.projection import build_projection_pack

    root, project = _copy_repo(tmp_path)
    resolved = _resolved(root, project, runtime="CHATGPT")
    build_projection_pack(root, project, resolved, runtime="CHATGPT")
    pack = root / "generated/projections/chatgpt/project-fixture"
    stored = json.loads((pack / "resolved-context.json").read_text(encoding="utf-8"))
    assert stored == resolved


def test_projection_rebuild_is_atomic_when_materialization_fails(tmp_path: Path, monkeypatch):
    from evolution_harness import projection

    root, project = _copy_repo(tmp_path)
    resolved = _resolved(root, project, runtime="CODEX")
    projection.build_projection_pack(root, project, resolved, runtime="CODEX")
    pack = root / "generated/projections/codex/project-fixture"
    before = {path.relative_to(pack).as_posix(): path.read_bytes() for path in pack.rglob("*") if path.is_file()}

    def fail_materialization(*args, **kwargs):
        raise RuntimeError("injected projection failure")

    monkeypatch.setattr(projection, "materialize_discussion_contract", fail_materialization)
    with pytest.raises(RuntimeError, match="injected projection failure"):
        projection.build_projection_pack(root, project, resolved, runtime="CODEX")

    after = {path.relative_to(pack).as_posix(): path.read_bytes() for path in pack.rglob("*") if path.is_file()}
    assert after == before
    assert not list(pack.parent.glob(".project-fixture.*"))


def test_projection_rejects_resolved_project_path_escape(tmp_path: Path):
    from evolution_harness.projection import ProjectionError, build_projection_pack

    root, project = _copy_repo(tmp_path)
    resolved = _resolved(root, project, runtime="CODEX")
    victim = tmp_path / "victim"
    victim.mkdir()
    sentinel = victim / "sentinel.txt"
    sentinel.write_text("preserve\n", encoding="utf-8")
    resolved["project"] = str(victim)

    with pytest.raises(ProjectionError, match="resolved context project"):
        build_projection_pack(root, project, resolved, runtime="CODEX")
    assert sentinel.read_text(encoding="utf-8") == "preserve\n"


def test_projection_rejects_resolved_context_not_produced_by_current_resolver(tmp_path: Path):
    from evolution_harness.projection import ProjectionError, build_projection_pack

    root, project = _copy_repo(tmp_path)
    resolved = _resolved(root, project, runtime="CODEX")
    resolved["requestedOutput"] = "tampered output with stale selection identity"

    with pytest.raises(ProjectionError, match="current resolver"):
        build_projection_pack(root, project, resolved, runtime="CODEX")


def test_projection_freshness_can_bind_expected_resolution_request(tmp_path: Path):
    from evolution_harness.projection import build_projection_pack, check_projection_freshness
    from evolution_harness.resolver import resolve_design_context

    root, project = _copy_repo(tmp_path)
    resolved = _resolved(root, project, runtime="CODEX")
    build_projection_pack(root, project, resolved, runtime="CODEX")
    changed_request = resolve_design_context(
        root,
        project,
        intent="architecture-review",
        topic="resolver-mvp",
        requested_output="different output contract",
        runtime="CODEX",
    )
    freshness = check_projection_freshness(
        root,
        project,
        runtime="CODEX",
        expected_resolution_id=changed_request["resolutionId"],
    )
    assert not freshness.fresh
    assert "resolution-context-drift" in freshness.reasons


def test_projection_freshness_never_hashes_manifest_path_outside_pack(tmp_path: Path, monkeypatch):
    from evolution_harness import projection

    root, project = _copy_repo(tmp_path)
    resolved = _resolved(root, project, runtime="CODEX")
    projection.build_projection_pack(root, project, resolved, runtime="CODEX")
    pack = root / "generated/projections/codex/project-fixture"
    victim = tmp_path / "excluded-secret.txt"
    victim.write_text("must not be read or hashed\n", encoding="utf-8")
    manifest_path = pack / "projection-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["generatedFiles"] = [
        {
            "path": Path(os.path.relpath(victim, pack)).as_posix(),
            "sha256": "0" * 64,
        }
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    original_hash = projection.file_sha256
    hashed: list[Path] = []

    def observe_hash(path: Path) -> str:
        hashed.append(path.resolve())
        return original_hash(path)

    monkeypatch.setattr(projection, "file_sha256", observe_hash)
    freshness = projection.check_projection_freshness(root, project, runtime="CODEX")

    assert not freshness.fresh
    assert freshness.reasons == ("projection-integrity-drift",)
    assert victim.resolve() not in hashed


def test_projection_reentry_recovers_interrupted_directory_swap(tmp_path: Path):
    from evolution_harness import projection

    root, project = _copy_repo(tmp_path)
    resolved = _resolved(root, project, runtime="CODEX")
    projection.build_projection_pack(root, project, resolved, runtime="CODEX")
    target = root / "generated/projections/codex/project-fixture"
    token = "a" * 32
    backup = target.parent / f".project-fixture.backup-{token}"
    target.replace(backup)
    orphan = target.parent / f".project-fixture.tmp-{token}"
    orphan.mkdir()
    (orphan / "partial.txt").write_text("partial\n", encoding="utf-8")
    journal = {
        "schemaVersion": "projection-swap-transaction/v1",
        "phase": "PREPARED",
        "runtime": "CODEX",
        "project": "project-fixture",
        "token": token,
        "hadTarget": True,
        "temporaryName": orphan.name,
        "backupName": backup.name,
    }
    journal_path = target.parent / ".project-fixture.swap-transaction.json"
    from evolution_harness.anchored_fs import AnchoredRoot

    with AnchoredRoot(root) as filesystem:
        filesystem.write_bytes(journal_path.relative_to(root).as_posix(), projection.deterministic_json_bytes(journal))

    projection.build_projection_pack(root, project, resolved, runtime="CODEX")
    assert target.is_dir()
    assert not backup.exists()
    assert not orphan.exists()
    assert not journal_path.exists()


def test_projection_rejects_second_writer_for_same_pack(tmp_path: Path):
    from evolution_harness import projection
    from evolution_harness.process_lock import exclusive_process_lock, process_lock_identity

    root, project = _copy_repo(tmp_path)
    resolved = _resolved(root, project, runtime="CODEX")
    projection.build_projection_pack(root, project, resolved, runtime="CODEX")
    target = root / "generated/projections/codex/project-fixture"
    before = {path.relative_to(target).as_posix(): path.read_bytes() for path in target.rglob("*") if path.is_file()}
    identity = process_lock_identity("projection-pack", target)

    with exclusive_process_lock(identity):
        with pytest.raises(projection.ProjectionError, match="concurrent projection build rejected"):
            projection.build_projection_pack(root, project, resolved, runtime="CODEX")

    after = {path.relative_to(target).as_posix(): path.read_bytes() for path in target.rglob("*") if path.is_file()}
    assert after == before


def test_projection_rejects_symlinked_generated_output_parent(tmp_path: Path):
    from evolution_harness.projection import ProjectionError, build_projection_pack

    root, project = _copy_repo(tmp_path)
    resolved = _resolved(root, project, runtime="CODEX")
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "generated").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ProjectionError, match="output path contains a symlink"):
        build_projection_pack(root, project, resolved, runtime="CODEX")

    assert not any(outside.iterdir())


def test_projection_build_cannot_follow_output_symlink_inserted_after_path_check(tmp_path: Path, monkeypatch):
    from evolution_harness import projection

    root, project = _copy_repo(tmp_path)
    resolved = _resolved(root, project, runtime="CODEX")
    outside = tmp_path / "outside"
    outside.mkdir()
    original_target = projection._projection_target
    inserted = False

    def insert_symlink_after_check(*args, **kwargs):
        nonlocal inserted
        result = original_target(*args, **kwargs)
        if not inserted:
            inserted = True
            runtime_root = root / "generated/projections/codex"
            runtime_root.parent.mkdir(parents=True)
            runtime_root.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(projection, "_projection_target", insert_symlink_after_check)

    with pytest.raises(projection.ProjectionError, match="symlink|anchored"):
        projection.build_projection_pack(root, project, resolved, runtime="CODEX")

    assert not any(outside.iterdir())
