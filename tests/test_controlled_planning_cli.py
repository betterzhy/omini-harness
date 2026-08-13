from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
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


def _filesystem_snapshot(
    root: Path,
) -> dict[str, tuple[str, bytes | None, str | None]]:
    snapshot: dict[str, tuple[str, bytes | None, str | None]] = {}

    def visit(directory: Path) -> None:
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            path = Path(entry.path)
            relative_name = path.relative_to(root).as_posix()
            if entry.is_symlink():
                snapshot[relative_name] = ("symlink", None, os.readlink(path))
            elif entry.is_dir(follow_symlinks=False):
                snapshot[relative_name] = ("dir", None, None)
                visit(path)
            elif entry.is_file(follow_symlinks=False):
                snapshot[relative_name] = ("file", path.read_bytes(), None)
            else:
                raise AssertionError(f"unexpected filesystem entry: {path}")

    visit(root)
    return snapshot


@pytest.mark.parametrize(
    "mutation",
    ["sibling-file", "empty-directory", "symlink-target", "entry-type"],
)
def test_no_write_snapshot_detects_every_filesystem_entry_mutation(
    tmp_path: Path, mutation: str
):
    root = tmp_path / "snapshot-root"
    root.mkdir()
    if mutation == "symlink-target":
        (root / "target-a").write_bytes(b"same")
        (root / "target-b").write_bytes(b"same")
        (root / "entry").symlink_to("target-a")
    elif mutation == "entry-type":
        (root / "entry").mkdir()
    before = _filesystem_snapshot(root)

    if mutation == "sibling-file":
        (root / "sibling.txt").write_bytes(b"created")
    elif mutation == "empty-directory":
        (root / "empty").mkdir()
    elif mutation == "symlink-target":
        (root / "entry").unlink()
        (root / "entry").symlink_to("target-b")
    else:
        (root / "entry").rmdir()
        (root / "entry").write_bytes(b"")

    assert before != _filesystem_snapshot(root)


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
    request_directory = tmp_path / "request"
    request_directory.mkdir()
    request_path = request_directory / "controlled-request.yaml"
    _write_request(request_path, controlled_factory.request(controlled_factory.descriptor()))
    repository_before = _filesystem_snapshot(root)
    request_before = _filesystem_snapshot(request_directory)

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
    assert repository_before == _filesystem_snapshot(root)
    assert request_before == _filesystem_snapshot(request_directory)


def test_planning_cli_rejects_partial_descriptor_without_writes(
    tmp_path: Path, controlled_factory
):
    root = _copy_schema_root(tmp_path)
    request_directory = tmp_path / "request"
    request_directory.mkdir()
    request_path = request_directory / "controlled-request.yaml"
    request = controlled_factory.request(controlled_factory.descriptor())
    del request["slices"][0]["bindingSet"]
    _write_request(request_path, request)
    repository_before = _filesystem_snapshot(root)
    request_before = _filesystem_snapshot(request_directory)

    result = _run_cli(
        root, "planning", "plan", "--request", str(request_path), "--format", "json"
    )

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "bindingSet" in payload["data"]["message"]
    assert repository_before == _filesystem_snapshot(root)
    assert request_before == _filesystem_snapshot(request_directory)


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
