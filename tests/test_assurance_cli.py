from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from capability_pack_test_support import retain_web_registration_fixture


def _copy_repo(tmp_path: Path) -> tuple[Path, Path]:
    source = Path(__file__).parents[1]
    root = tmp_path / "repo"
    for name in [
        "core",
        "design",
        "engineering",
        "runtime",
        "examples",
        "integrations",
        "contracts",
        "policies",
        "skills",
        "verification",
        "generated",
    ]:
        src = source / name
        if src.exists():
            shutil.copytree(src, root / name)
    retain_web_registration_fixture(root)
    return root, root / "examples/project-fixture"


def _make_external_pack_source_unavailable(root: Path, tmp_path: Path) -> None:
    registration_path = root / "core/registries/capability-packs.yaml"
    registration = registration_path.read_text(encoding="utf-8")
    registrations = yaml.safe_load(registration)
    repository_path = registrations[0]["source"]["repositoryPath"]
    unavailable_path = str(tmp_path / "unavailable-pack")

    assert repository_path in registration
    registration_path.write_text(
        registration.replace(repository_path, unavailable_path), encoding="utf-8"
    )


def test_structural_validation_separates_mechanical_gate_from_semantic_quality(tmp_path: Path):
    from evolution_harness.assurance import structural_validate
    from evolution_harness.catalog import build_all_catalogs
    from evolution_harness.project import build_capability_lock
    from evolution_harness.projection import build_projection_pack
    from evolution_harness.registry import build_all_registries
    from evolution_harness.resolver import resolve_design_context

    root, project = _copy_repo(tmp_path)
    build_all_registries(root, write=True)
    build_all_catalogs(root, write=True)
    build_capability_lock(root, project, write=True)
    for runtime in ["CHATGPT", "CODEX"]:
        resolved = resolve_design_context(root, project, intent="architecture-review", topic="resolver-mvp", requested_output="review findings", runtime=runtime)
        build_projection_pack(root, project, resolved, runtime=runtime)
    report = structural_validate(root, project_roots=[project], check_generated=True)
    assert report["structuralGate"] == "PASS"
    assert report["semanticGate"] == "NOT_ASSERTED_BY_CI"
    assert report["issues"] == []
    assert report["integrationCount"] == 3


def test_internal_only_structural_validation_without_generated_check_ignores_unavailable_pack_source(
    tmp_path: Path,
):
    from evolution_harness.assurance import structural_validate

    root, _ = _copy_repo(tmp_path)
    # This fixture verifies generic internal-only assurance.  The external
    # Cognitura sidecar has its own Pack-source validation contract.
    shutil.rmtree(root / "integrations" / "cognitura-shadow")
    _make_external_pack_source_unavailable(root, tmp_path)

    report = structural_validate(root, check_generated=False)

    assert report["structuralGate"] == "PASS"
    assert report["issues"] == []
    assert report["capabilityCount"] == 10


def test_structural_validation_detects_generated_registry_drift(tmp_path: Path):
    from evolution_harness.assurance import structural_validate
    from evolution_harness.catalog import build_all_catalogs
    from evolution_harness.registry import build_all_registries

    root, project = _copy_repo(tmp_path)
    build_all_registries(root, write=True)
    build_all_catalogs(root, write=True)
    registry = root / "generated/registries/design-registry.json"
    registry.write_text(registry.read_text(encoding="utf-8") + "manual drift\n", encoding="utf-8")
    report = structural_validate(root, project_roots=[project], check_generated=True)
    assert report["structuralGate"] == "FAIL"
    assert any(issue["code"] == "GENERATED_DRIFT" for issue in report["issues"])


def test_structural_validation_detects_capability_pack_registry_drift(tmp_path: Path):
    from evolution_harness.assurance import structural_validate
    from evolution_harness.catalog import build_all_catalogs
    from evolution_harness.registry import build_all_registries

    root, _ = _copy_repo(tmp_path)
    build_all_registries(root, write=True)
    build_all_catalogs(root, write=True)
    structural_validate(root, check_generated=False)
    generated = root / "generated/registries/capability-pack-registry.json"
    generated.write_text("{}\n", encoding="utf-8")
    result = structural_validate(root, check_generated=True)
    assert result["structuralGate"] == "FAIL"
    assert any(
        "capability-pack-registry.json" in issue.get("path", "")
        for issue in result["issues"]
    )


def _run_module(root: Path, module: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    source_src = Path(__file__).parents[1] / "src"
    env["PYTHONPATH"] = str(source_src)
    return subprocess.run([sys.executable, "-m", module, "--repository-root", str(root), *args], text=True, capture_output=True, env=env)


def test_validate_cli_reports_unavailable_pack_as_generated_failure(tmp_path: Path):
    root, _ = _copy_repo(tmp_path)
    _make_external_pack_source_unavailable(root, tmp_path)

    result = _run_module(
        root,
        "evolution_harness.cli",
        "validate",
        "--check-generated",
        "--format",
        "json",
    )

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    report = payload["data"]
    assert report["structuralGate"] == "FAIL"
    assert report["capabilityCount"] == 10
    assert any(
        issue["code"] == "GENERATED_CHECK_FAILED"
        and "capability pack source root is unavailable" in issue["message"]
        for issue in report["issues"]
    )
    assert all(issue["code"] != "ENGINEERING_INVALID" for issue in report["issues"])


def test_harness_cli_validate_and_resolve_json(tmp_path: Path):
    root, project = _copy_repo(tmp_path)
    result = _run_module(root, "evolution_harness.cli", "validate", "--format", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schemaVersion"] == "harness-cli/v1"
    assert payload["ok"] is True
    assert payload["data"]["structuralGate"] == "PASS"

    result = _run_module(
        root, "evolution_harness.cli", "resolve",
        "--project", str(project), "--intent", "architecture-review", "--topic", "resolver-mvp",
        "--output", "review findings", "--runtime", "CHATGPT", "--explain", "--format", "json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    selected = {item["id"] for item in payload["data"]["selectedCapabilities"]}
    assert "skill:agent-design:architecture-review" in selected
    assert payload["data"]["explain"]["selected"]


def test_engineering_compat_cli_doctor_preserves_domain_boundary(tmp_path: Path):
    root, _ = _copy_repo(tmp_path)
    result = _run_module(root, "engineering_cli.cli", "doctor", "--ci", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["engineeringDomain"] == "PASS"
