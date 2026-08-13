from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


def _copy_schema_root(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    shutil.copytree(source / "core", root / "core")
    return root


def _copy_repo(tmp_path: Path) -> tuple[Path, Path]:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    for name in [
        "core",
        "design",
        "engineering",
        "runtime",
        "contracts",
        "policies",
        "skills",
        "verification",
    ]:
        source_path = source / name
        if source_path.exists():
            shutil.copytree(source_path, root / name)
    shutil.copytree(
        source / "examples/project-fixture", root / "examples/project-fixture"
    )
    return root, root / "examples/project-fixture"


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _run_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "evolution_harness.cli",
            "--repository-root",
            str(root),
            *args,
        ],
        text=True,
        capture_output=True,
        env=environment,
    )


def _write_request(path: Path, request: dict) -> None:
    path.write_text(yaml.safe_dump(request, sort_keys=False), encoding="utf-8")


def test_planning_cli_emits_provisional_plan_without_writing_inputs(
    tmp_path: Path, controlled_factory
):
    root = _copy_schema_root(tmp_path)
    request_path = tmp_path / "controlled-request.yaml"
    _write_request(request_path, controlled_factory.request(controlled_factory.descriptor()))
    before = _tree_bytes(root)
    request_before = request_path.read_bytes()

    result = _run_cli(
        root, "planning", "plan", "--request", str(request_path), "--format", "json"
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schemaVersion"] == "harness-cli/v1"
    assert payload["ok"] is True
    assert payload["command"] == "planning plan"
    assert payload["data"]["executionPlan"]["provisional"] is True
    assert payload["data"]["executionPlan"]["requiresCoordinatorRecheck"] is True
    assert before == _tree_bytes(root)
    assert request_before == request_path.read_bytes()


def test_planning_cli_rejects_partial_descriptor_without_writes(
    tmp_path: Path, controlled_factory
):
    root = _copy_schema_root(tmp_path)
    request_path = tmp_path / "controlled-request.yaml"
    request = controlled_factory.request(controlled_factory.descriptor())
    del request["slices"][0]["bindingSet"]
    _write_request(request_path, request)
    before = _tree_bytes(root)
    request_before = request_path.read_bytes()

    result = _run_cli(
        root, "planning", "plan", "--request", str(request_path), "--format", "json"
    )

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "bindingSet" in payload["data"]["message"]
    assert before == _tree_bytes(root)
    assert request_before == request_path.read_bytes()


def test_planning_cli_rejects_snapshot_fingerprint_drift(tmp_path: Path, controlled_factory):
    root = _copy_schema_root(tmp_path)
    request_path = tmp_path / "controlled-request.yaml"
    request = controlled_factory.request(controlled_factory.descriptor())
    request["authoritySnapshot"]["snapshotFingerprint"] = "sha256:" + "0" * 64
    _write_request(request_path, request)

    result = _run_cli(
        root, "planning", "plan", "--request", str(request_path), "--format", "json"
    )

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["data"]["code"] == "AUTHORITY_SNAPSHOT_FINGERPRINT_MISMATCH"


def test_existing_validate_and_resolve_cli_contracts_are_unchanged(tmp_path: Path):
    root, project = _copy_repo(tmp_path)
    assert not (root / "integrations").exists()
    assert [path.name for path in (root / "examples").iterdir()] == ["project-fixture"]

    validate = _run_cli(root, "validate", "--format", "json")
    assert validate.returncode == 0, validate.stderr
    validate_payload = json.loads(validate.stdout)
    assert validate_payload["schemaVersion"] == "harness-cli/v1"
    assert validate_payload["command"] == "validate"
    assert validate_payload["ok"] is True

    resolve = _run_cli(
        root,
        "resolve",
        "--project",
        str(project),
        "--intent",
        "architecture-review",
        "--topic",
        "resolver-mvp",
        "--output",
        "review findings",
        "--runtime",
        "CHATGPT",
        "--format",
        "json",
    )
    assert resolve.returncode == 0, resolve.stderr
    resolve_payload = json.loads(resolve.stdout)
    assert resolve_payload["schemaVersion"] == "harness-cli/v1"
    assert resolve_payload["command"] == "resolve"
    assert resolve_payload["ok"] is True
