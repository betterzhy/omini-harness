from __future__ import annotations

import shutil
from pathlib import Path

import yaml


def _copy_repo(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    shutil.copytree(source / "core", root / "core")
    shutil.copytree(source / "design", root / "design")
    return root


def test_revalidation_reports_due_and_triggered_without_mutating_capability(tmp_path: Path):
    from evolution_harness.revalidation import check_revalidation

    root = _copy_repo(tmp_path)
    asset_path = root / "design/capabilities/skills/architecture-review/asset.yaml"
    asset = yaml.safe_load(asset_path.read_text(encoding="utf-8"))
    asset["reviewAfter"] = "2026-08-01"
    asset["revalidationTriggers"] = ["MODEL_UPGRADE"]
    asset_path.write_text(yaml.safe_dump(asset, sort_keys=False), encoding="utf-8")
    before = asset_path.read_bytes()
    result = check_revalidation(root, as_of="2026-08-11", triggers=["MODEL_UPGRADE"])
    item = next(x for x in result["capabilities"] if x["id"] == "skill:agent-design:architecture-review")
    assert item["status"] == "REQUIRED"
    assert set(item["reasons"]) == {"review-due", "trigger:MODEL_UPGRADE"}
    assert asset_path.read_bytes() == before


def test_revalidation_treats_questioned_validity_as_required(tmp_path: Path):
    from evolution_harness.revalidation import check_revalidation

    root = _copy_repo(tmp_path)
    asset_path = root / "design/capabilities/skills/architecture-review/asset.yaml"
    asset = yaml.safe_load(asset_path.read_text(encoding="utf-8"))
    asset["validity"] = "QUESTIONED"
    asset_path.write_text(yaml.safe_dump(asset, sort_keys=False), encoding="utf-8")
    result = check_revalidation(root, as_of="2026-08-11")
    item = next(x for x in result["capabilities"] if x["id"] == "skill:agent-design:architecture-review")
    assert item["status"] == "REQUIRED"
    assert "validity:QUESTIONED" in item["reasons"]
