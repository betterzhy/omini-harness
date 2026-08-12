from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml


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
    assert not check.fresh and "generated-file-drift" in check.reasons
    build_projection_pack(root, project, resolved, runtime="CHATGPT")
    assert skill.read_text(encoding="utf-8") == original
    canonical = root / "design/capabilities/skills/architecture-review/content.md"
    canonical.write_text(canonical.read_text(encoding="utf-8") + "\ncanonical change without projection rebuild\n", encoding="utf-8")
    check = check_projection_freshness(root, project, runtime="CHATGPT")
    assert not check.fresh and "source-capability-hash-changed" in check.reasons


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
