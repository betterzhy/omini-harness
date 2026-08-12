from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


def _write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repository = Path(__file__).parents[1]
    root = tmp_path / "harness"
    shutil.copytree(repository / "core", root / "core")
    integration = root / "integrations/sample-shadow"
    source = tmp_path / "source-project"
    source.mkdir()
    (source / "status.md").write_text(
        "# Status\n\nCurrentStage = READY\nExecutionAllowed = NO_WINDOW_CLOSED\n",
        encoding="utf-8",
    )
    _write_yaml(source / "slice.yaml", {"ProgressAuthority": "THIS_DOCUMENT", "SliceStatus": "CLOSED"})
    (source / "derived.md").write_text("ExecutionAllowed = YES\n", encoding="utf-8")
    (source / "private").mkdir()
    (source / "private/secret.md").write_text("Secret = value\n", encoding="utf-8")

    _write_yaml(
        integration / "integration.yaml",
        {
            "schemaVersion": "project-integration/v1",
            "id": "sample-shadow",
            "projectId": "sample-shadow",
            "sourceAccess": "READ_ONLY",
            "controlPlanePath": "control-plane",
            "authorityMapPath": "authority-map.yaml",
            "runtime": "CODEX",
            "excludedPaths": ["private/**"],
        },
    )
    _write_yaml(
        integration / "authority-map.yaml",
        {
            "schemaVersion": "project-authority-map/v1",
            "authorities": [
                {
                    "id": "global-status",
                    "path": "status.md",
                    "format": "MARKDOWN_KV",
                    "role": "CANONICAL",
                    "required": True,
                    "owns": ["project.stage", "permission.execute"],
                    "selectors": {
                        "project.stage": {"key": "CurrentStage", "required": True},
                        "permission.execute": {
                            "key": "ExecutionAllowed",
                            "required": True,
                            "normalization": {
                                "rules": [
                                    {"operator": "PREFIX", "expected": "YES", "value": "ALLOW"},
                                    {"operator": "PREFIX", "expected": "NO", "value": "DENY"},
                                ],
                                "default": "UNKNOWN",
                            },
                        },
                    },
                },
                {
                    "id": "slice-status",
                    "path": "slice.yaml",
                    "format": "YAML",
                    "role": "SPECIALIZED",
                    "required": True,
                    "owns": ["slice.status"],
                    "selectors": {
                        "slice.status": {"key": "SliceStatus", "required": True},
                    },
                },
                {
                    "id": "derived-status",
                    "path": "derived.md",
                    "format": "MARKDOWN_KV",
                    "role": "DERIVED",
                    "required": False,
                    "owns": [],
                    "selectors": {},
                },
            ],
            "requiredFacts": ["project.stage", "permission.execute", "slice.status"],
        },
    )
    return root, integration, source


def test_snapshot_extracts_owned_facts_and_normalizes_permission(tmp_path: Path):
    from evolution_harness.authority import build_authority_snapshot

    root, integration, source = _fixture(tmp_path)
    snapshot = build_authority_snapshot(root, integration, source)
    assert snapshot["gate"] == "PASS"
    assert snapshot["facts"]["project.stage"]["rawValue"] == "READY"
    assert snapshot["facts"]["permission.execute"]["normalizedValue"] == "DENY"
    assert snapshot["facts"]["slice.status"]["owner"] == "slice-status"
    assert snapshot["snapshotFingerprint"].startswith("sha256:")
    assert snapshot["sourceRevision"]["kind"] in {"GIT", "CONTENT"}


def test_snapshot_fingerprint_changes_when_authority_changes(tmp_path: Path):
    from evolution_harness.authority import build_authority_snapshot

    root, integration, source = _fixture(tmp_path)
    before = build_authority_snapshot(root, integration, source)
    (source / "status.md").write_text(
        "CurrentStage = READY\nExecutionAllowed = YES_EXPLICIT\n",
        encoding="utf-8",
    )
    after = build_authority_snapshot(root, integration, source)
    assert before["snapshotFingerprint"] != after["snapshotFingerprint"]
    assert after["facts"]["permission.execute"]["normalizedValue"] == "ALLOW"


def test_multiple_fact_owners_and_conflicting_values_fail_closed(tmp_path: Path):
    from evolution_harness.authority import build_authority_snapshot

    root, integration, source = _fixture(tmp_path)
    path = integration / "authority-map.yaml"
    authority_map = yaml.safe_load(path.read_text(encoding="utf-8"))
    authority_map["authorities"][2]["role"] = "CANONICAL"
    authority_map["authorities"][2]["owns"] = ["permission.execute"]
    authority_map["authorities"][2]["selectors"] = {
        "permission.execute": {"key": "ExecutionAllowed", "required": True}
    }
    _write_yaml(path, authority_map)

    snapshot = build_authority_snapshot(root, integration, source)
    assert snapshot["gate"] == "NO_GO"
    assert any(item["type"] == "MULTIPLE_FACT_OWNERS" for item in snapshot["conflicts"])


def test_missing_required_fact_fails_closed(tmp_path: Path):
    from evolution_harness.authority import build_authority_snapshot

    root, integration, source = _fixture(tmp_path)
    (source / "slice.yaml").write_text("ProgressAuthority: THIS_DOCUMENT\n", encoding="utf-8")
    snapshot = build_authority_snapshot(root, integration, source)
    assert snapshot["gate"] == "NO_GO"
    assert "slice.status" in snapshot["missingFacts"]


def test_excluded_authority_path_is_rejected_before_read(tmp_path: Path):
    from evolution_harness.authority import IntegrationAuthorityError, build_authority_snapshot

    root, integration, source = _fixture(tmp_path)
    path = integration / "authority-map.yaml"
    authority_map = yaml.safe_load(path.read_text(encoding="utf-8"))
    authority_map["authorities"][0]["path"] = "private/secret.md"
    _write_yaml(path, authority_map)
    with pytest.raises(IntegrationAuthorityError, match="excluded"):
        build_authority_snapshot(root, integration, source)


def test_derived_authority_cannot_own_facts(tmp_path: Path):
    from evolution_harness.authority import IntegrationAuthorityError, build_authority_snapshot

    root, integration, source = _fixture(tmp_path)
    path = integration / "authority-map.yaml"
    authority_map = yaml.safe_load(path.read_text(encoding="utf-8"))
    authority_map["authorities"][2]["owns"] = ["permission.execute"]
    authority_map["authorities"][2]["selectors"] = {
        "permission.execute": {"key": "ExecutionAllowed", "required": True}
    }
    _write_yaml(path, authority_map)
    with pytest.raises(IntegrationAuthorityError, match="derived"):
        build_authority_snapshot(root, integration, source)


def test_excluded_authority_cannot_be_read_through_in_root_symlink(tmp_path: Path):
    from evolution_harness.authority import IntegrationAuthorityError, build_authority_snapshot

    root, integration, source = _fixture(tmp_path)
    (source / "alias").symlink_to(source / "private", target_is_directory=True)
    path = integration / "authority-map.yaml"
    authority_map = yaml.safe_load(path.read_text(encoding="utf-8"))
    authority_map["authorities"][0]["path"] = "alias/secret.md"
    _write_yaml(path, authority_map)

    with pytest.raises(IntegrationAuthorityError, match="symlink|excluded"):
        build_authority_snapshot(root, integration, source)


def test_git_source_revision_marks_dirty_authority_set(tmp_path: Path):
    from evolution_harness.authority import build_authority_snapshot

    root, integration, source = _fixture(tmp_path)
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "add", "status.md", "slice.yaml", "derived.md"], check=True)
    subprocess.run(
        ["git", "-C", str(source), "-c", "user.name=Harness Test", "-c", "user.email=harness@example.invalid", "commit", "-q", "-m", "baseline"],
        check=True,
    )
    clean = build_authority_snapshot(root, integration, source)
    assert clean["sourceRevision"]["authoritySetStatus"] == "CLEAN_FOR_AUTHORITY_SET"

    (source / "status.md").write_text(
        "CurrentStage = READY\nExecutionAllowed = YES_EXPLICIT\n", encoding="utf-8"
    )
    dirty = build_authority_snapshot(root, integration, source)
    assert dirty["sourceRevision"]["authoritySetStatus"] == "DIRTY_AUTHORITY_SET"
    assert dirty["sourceRevision"]["head"] == clean["sourceRevision"]["head"]
    assert dirty["sourceRevision"]["authoritySetDigest"] != clean["sourceRevision"]["authoritySetDigest"]


def test_authority_hash_and_extracted_facts_come_from_one_byte_snapshot(tmp_path: Path, monkeypatch):
    from evolution_harness import authority
    from evolution_harness.anchored_fs import AnchoredRoot
    from evolution_harness.hashing import sha256_bytes

    root, integration, source = _fixture(tmp_path)
    status = source / "status.md"
    before = status.read_bytes()
    after = b"CurrentStage = READY\nExecutionAllowed = YES_EXPLICIT\n"
    original_read = AnchoredRoot.read_bytes
    changed = False

    def change_after_read(self, relative: str) -> bytes:
        nonlocal changed
        data = original_read(self, relative)
        if self.root == source and relative == "status.md" and not changed:
            changed = True
            status.write_bytes(after)
        return data

    monkeypatch.setattr(AnchoredRoot, "read_bytes", change_after_read)
    snapshot = authority.build_authority_snapshot(root, integration, source)
    raw = snapshot["facts"]["permission.execute"]["rawValue"]
    authority_hash = next(item["sha256"] for item in snapshot["authorities"] if item["id"] == "global-status")
    expected_bytes = before if raw.startswith("NO") else after

    assert authority_hash == sha256_bytes(expected_bytes)
