from __future__ import annotations

import json
import shutil
from pathlib import Path


def _copy_repo(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    for name in ["core", "design", "engineering", "contracts", "policies", "verification", "skills"]:
        src = source / name
        if src.exists():
            shutil.copytree(src, root / name)
    return root


def test_design_registry_is_deterministic_and_body_free(tmp_path: Path):
    from evolution_harness.registry import build_design_registry

    root = _copy_repo(tmp_path)
    first = build_design_registry(root, write=True)
    path = root / "generated/registries/design-registry.json"
    bytes1 = path.read_bytes()
    second = build_design_registry(root, write=True)
    assert path.read_bytes() == bytes1
    assert first == second
    assert len(first["entries"]) == 10
    assert all("content" not in entry and "body" not in entry for entry in first["entries"])
    assert all({"id", "version", "contentHash", "location", "scope"} <= set(entry) for entry in first["entries"])


def test_learning_registry_indexes_experience_and_candidate_but_catalog_does_not(tmp_path: Path):
    from evolution_harness.catalog import build_design_active_catalog
    from evolution_harness.registry import build_design_learning_registry

    root = _copy_repo(tmp_path)
    learning = build_design_learning_registry(root, write=True)
    catalog = build_design_active_catalog(root, write=True)
    assert len(learning["entries"]) == 5
    assert {e["entryType"] for e in learning["entries"]} == {"EXPERIENCE", "CANDIDATE"}
    serialized = json.dumps(catalog)
    assert "experience:" not in serialized
    assert "candidate:" not in serialized


def test_active_catalog_selects_only_highest_eligible_version_for_same_identity(tmp_path: Path):
    from evolution_harness.catalog import build_design_active_catalog

    root = _copy_repo(tmp_path)
    source = root / "design/capabilities/skills/architecture-review"
    version_dir = source / "versions/1.1.0"
    version_dir.mkdir(parents=True)
    asset = (source / "asset.yaml").read_text(encoding="utf-8").replace("version: 1.0.0", "version: 1.1.0", 1)
    (version_dir / "asset.yaml").write_text(asset, encoding="utf-8")
    (version_dir / "content.md").write_text((source / "content.md").read_text(encoding="utf-8") + "\nVersion fixture.\n", encoding="utf-8")
    catalog = build_design_active_catalog(root, write=False)
    matches = [e for e in catalog["entries"] if e["id"] == "skill:agent-design:architecture-review"]
    assert len(matches) == 1
    assert matches[0]["version"] == "1.1.0"


def test_active_catalog_excludes_deprecated_invalid_and_identity_superseded(tmp_path: Path):
    from evolution_harness.catalog import build_design_active_catalog

    root = _copy_repo(tmp_path)
    deprecated = root / "design/capabilities/skills/baseline-finalization/asset.yaml"
    text = deprecated.read_text(encoding="utf-8").replace("lifecycle: ACTIVE", "lifecycle: DEPRECATED", 1)
    deprecated.write_text(text, encoding="utf-8")
    invalid = root / "design/capabilities/skills/next-topic-routing/asset.yaml"
    text = invalid.read_text(encoding="utf-8").replace("validity: VALID", "validity: INVALID", 1)
    invalid.write_text(text, encoding="utf-8")
    # A current capability can supersede another identity without erasing its historical registry entry.
    arch = root / "design/capabilities/skills/architecture-review/asset.yaml"
    text = arch.read_text(encoding="utf-8").replace("  supersedes: []", "  supersedes:\n  - skill:agent-design:design-closure-assessment", 1)
    arch.write_text(text, encoding="utf-8")
    catalog = build_design_active_catalog(root, write=False)
    ids = {e["id"] for e in catalog["entries"]}
    assert "skill:agent-design:baseline-finalization" not in ids
    assert "skill:agent-design:next-topic-routing" not in ids
    assert "skill:agent-design:design-closure-assessment" not in ids


def test_engineering_registry_and_catalog_remain_separate_domains(tmp_path: Path):
    from evolution_harness.catalog import build_engineering_active_catalog
    from evolution_harness.registry import build_engineering_registry

    root = _copy_repo(tmp_path)
    registry = build_engineering_registry(root, write=True)
    catalog = build_engineering_active_catalog(root, write=True)
    assert len(registry["entries"]) == 6
    assert len(catalog["entries"]) == 4
    assert all(entry["domain"] == "engineering" for entry in registry["entries"])
    assert all(not entry["id"].startswith(("principle:agent-design", "framework:agent-design")) for entry in registry["entries"])


def test_unified_catalog_is_projection_not_universal_registry(tmp_path: Path):
    from evolution_harness.catalog import build_all_catalogs

    root = _copy_repo(tmp_path)
    catalogs = build_all_catalogs(root, write=True)
    unified = catalogs["unified"]
    assert len(unified["entries"]) == 14
    assert {e["domain"] for e in unified["entries"]} == {"design", "engineering"}
    assert all("content" not in entry and "body" not in entry for entry in unified["entries"])
    assert (root / "generated/catalogs/unified-active-catalog.json").exists()


def test_generated_drift_check_detects_manual_edit_and_delete_rebuild_is_equivalent(tmp_path: Path):
    from evolution_harness.catalog import build_all_catalogs
    from evolution_harness.generated import check_generated_file
    from evolution_harness.registry import build_all_registries

    root = _copy_repo(tmp_path)
    build_all_registries(root, write=True)
    build_all_catalogs(root, write=True)
    path = root / "generated/registries/design-registry.json"
    baseline = path.read_bytes()
    assert check_generated_file(path, baseline).fresh
    path.write_text("{}\n", encoding="utf-8")
    assert not check_generated_file(path, baseline).fresh
    path.unlink()
    build_all_registries(root, write=True)
    assert path.read_bytes() == baseline
