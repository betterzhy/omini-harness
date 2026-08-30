from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from capability_pack_test_support import JAVA_CAPABILITY_ID, retain_web_registration_fixture
from evolution_harness.cli import main
from test_toolchain_provisioning import make_provision_harness


EXTERNAL_CAPABILITY_ID = "workflow:web-high-fidelity:reference-driven-visual-fidelity"
INACTIVE_CAPABILITY_ID = "workflow:inactive-pack:inactive-workflow"


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


def _relocate_external_pack_to_controlled_clone(root: Path, tmp_path: Path) -> Path:
    registration_path = root / "core/registries/capability-packs.yaml"
    registrations = yaml.safe_load(registration_path.read_text(encoding="utf-8"))
    assert len(registrations) == 1
    registration = registrations[0]
    source = tmp_path / "external-pack"
    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "--no-hardlinks",
            registration["source"]["repositoryPath"],
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "-q", "--detach", registration["source"]["commit"]],
        cwd=source,
        check=True,
        capture_output=True,
    )
    registration["source"]["repositoryPath"] = str(source)
    registration_path.write_text(
        yaml.safe_dump(registrations, sort_keys=False), encoding="utf-8"
    )
    return source


def _add_inactive_external_pack(root: Path, tmp_path: Path) -> Path:
    from evolution_harness.capability_pack_registry import (
        compute_capability_pack_content_digest,
    )

    source = tmp_path / "inactive-pack"
    (source / "skills/inactive-pack").mkdir(parents=True)
    (source / "scripts").mkdir()
    manifest = {
        "schemaVersion": "capability-pack/v1",
        "projectPackName": "inactive-pack",
        "skillName": "inactive-pack",
        "displayName": "Inactive Pack Fixture",
        "capabilityId": INACTIVE_CAPABILITY_ID,
        "version": "1.0.0",
        "contentDigestContract": "capability-pack-content/v1",
        "contentRoots": ["skills", "scripts"],
        "excludedContentRoots": ["skills/unused"],
        "skillPath": "skills/inactive-pack/SKILL.md",
        "validator": {
            "kind": "FIXED_CANDIDATE_GATE",
            "path": "scripts/verify-capability-pack",
            "argumentsContract": "CANDIDATE_COMMIT_TREE",
        },
    }
    (source / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (source / "capability-pack.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    (source / "skills/inactive-pack/SKILL.md").write_text(
        "# Inactive Pack Fixture\n", encoding="utf-8"
    )
    validator = source / "scripts/verify-capability-pack"
    validator.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "test \"$#\" -eq 2\n"
        "test \"$(git rev-parse HEAD)\" = \"$1\"\n"
        "test \"$(git rev-parse 'HEAD^{tree}')\" = \"$2\"\n"
        "test -z \"$(git status --porcelain)\"\n",
        encoding="utf-8",
    )
    validator.chmod(0o755)
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-q",
            "-m",
            "test: inactive Pack fixture",
        ],
        cwd=source,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    registration_path = root / "core/registries/capability-packs.yaml"
    registrations = yaml.safe_load(registration_path.read_text(encoding="utf-8"))
    registrations.append(
        {
            "schemaVersion": "capability-pack-registration/v1",
            "registrationId": "pack:inactive-pack",
            "capabilityId": INACTIVE_CAPABILITY_ID,
            "packVersion": "1.0.0",
            "status": "INACTIVE",
            "distributionStatus": "LOCAL_ONLY",
            "source": {
                "kind": "LOCAL_GIT",
                "repositoryId": "inactive-pack",
                "repositoryPath": str(source),
                "commit": commit,
                "tree": tree,
            },
            "resolvedContentDigest": compute_capability_pack_content_digest(
                source, manifest
            ),
            "validator": {
                "kind": "FIXED_CANDIDATE_GATE",
                "relativePath": "scripts/verify-capability-pack",
                "sha256": "sha256:"
                + hashlib.sha256(validator.read_bytes()).hexdigest(),
                "argumentsContract": "CANDIDATE_COMMIT_TREE",
            },
        }
    )
    registration_path.write_text(
        yaml.safe_dump(registrations, sort_keys=False), encoding="utf-8"
    )
    return source


def test_core_scope_does_not_touch_adoption_or_external_pack_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from evolution_harness import assurance
    from evolution_harness import capability_pack_registry

    root, _ = _copy_repo(tmp_path)
    _make_external_pack_source_unavailable(root, tmp_path)

    def forbidden(*_args, **_kwargs):
        pytest.fail("core scope touched adoption validation")

    monkeypatch.setattr(assurance, "load_capability_pack_registrations", forbidden)
    monkeypatch.setattr(assurance, "CapabilityVerificationSession", forbidden)
    monkeypatch.setattr(assurance, "_validate_integrations", forbidden)
    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", forbidden)

    report = assurance.structural_validate(
        root,
        scope="core",
        check_generated=True,
    )

    assert report["structuralGate"] == "PASS"
    assert report["issues"] == []
    assert report["integrationCount"] == 0


def test_validation_scopes_keep_unavailable_pack_in_owning_fault_domain(tmp_path: Path):
    from evolution_harness.assurance import structural_validate

    root, _ = _copy_repo(tmp_path)
    _make_external_pack_source_unavailable(root, tmp_path)
    core = structural_validate(root, scope="core", check_generated=True)
    adoption = structural_validate(root, scope="adoption", check_generated=True)
    aggregate = structural_validate(root, scope="all", check_generated=True)
    assert core["structuralGate"] == "PASS"
    assert core["integrationCount"] == 0
    for report in (adoption, aggregate):
        assert report["structuralGate"] == "FAIL"
        assert any(
            "capability pack source root is unavailable" in issue["message"]
            for issue in report["issues"]
        )


def test_validate_default_scope_is_byte_identical_to_explicit_all(tmp_path: Path):
    root, _ = _copy_repo(tmp_path)
    _make_external_pack_source_unavailable(root, tmp_path)
    default = _run_module(
        root,
        "evolution_harness.cli",
        "validate",
        "--check-generated",
        "--format",
        "json",
    )
    explicit = _run_module(
        root,
        "evolution_harness.cli",
        "validate",
        "--scope",
        "all",
        "--check-generated",
        "--format",
        "json",
    )
    assert (default.returncode, default.stdout, default.stderr) == (
        explicit.returncode,
        explicit.stdout,
        explicit.stderr,
    )


def test_core_generated_check_owns_local_registry_drift(tmp_path: Path):
    from evolution_harness.assurance import structural_validate

    root, _ = _copy_repo(tmp_path)
    registry = root / "generated/registries/design-registry.json"
    registry.write_bytes(registry.read_bytes() + b"manual drift\n")

    core = structural_validate(root, scope="core", check_generated=True)
    adoption = structural_validate(root, scope="adoption", check_generated=True)
    aggregate = structural_validate(root, scope="all", check_generated=True)

    assert core["structuralGate"] == "FAIL"
    assert aggregate["structuralGate"] == "FAIL"
    assert adoption["structuralGate"] == "PASS"
    for report in (core, aggregate):
        assert any(issue.get("path") == str(registry) for issue in report["issues"])
    assert all(issue.get("path") != str(registry) for issue in adoption["issues"])


def test_adoption_generated_check_owns_capability_pack_registry_drift(tmp_path: Path):
    from evolution_harness.assurance import structural_validate

    root, _ = _copy_repo(tmp_path)
    registry = root / "generated/registries/capability-pack-registry.json"
    registry.write_text("{}\n", encoding="utf-8")

    core = structural_validate(root, scope="core", check_generated=True)
    adoption = structural_validate(root, scope="adoption", check_generated=True)
    aggregate = structural_validate(root, scope="all", check_generated=True)

    assert core["structuralGate"] == "PASS"
    for report in (adoption, aggregate):
        assert report["structuralGate"] == "FAIL"
        assert any(issue.get("path") == str(registry) for issue in report["issues"])
    assert all(issue.get("path") != str(registry) for issue in core["issues"])


def test_validate_core_scope_rejects_project_argument(tmp_path: Path):
    root, project = _copy_repo(tmp_path)

    result = _run_module(
        root,
        "evolution_harness.cli",
        "validate",
        "--scope",
        "core",
        "--project",
        str(project),
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--scope core" in result.stderr
    assert "--project" in result.stderr


def test_web_only_copied_repository_fixture_excludes_java_pay_projection(tmp_path: Path):
    root, _ = _copy_repo(tmp_path)
    control = root / "integrations/pay-nexus-shadow/control-plane/.agent-evolution"
    binding = yaml.safe_load((control / "capabilities.yaml").read_text(encoding="utf-8"))
    lock = yaml.safe_load((control / "capabilities.lock.yaml").read_text(encoding="utf-8"))

    assert JAVA_CAPABILITY_ID not in binding["capabilities"]
    assert all(item["capabilityId"] != JAVA_CAPABILITY_ID for item in lock["capabilities"])
    assert lock["schemaVersion"] == "capability-lock/v1"
    assert not (root / "generated/projections/codex/pay-nexus-shadow").exists()


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


def test_structural_validation_reuses_one_external_pack_gate_without_report_or_write_drift(
    tmp_path: Path,
    monkeypatch,
):
    from evolution_harness import capability_pack_registry
    from evolution_harness.assurance import structural_validate
    from evolution_harness.catalog import build_all_catalogs
    from evolution_harness.project import build_capability_lock
    from evolution_harness.projection import build_projection_pack
    from evolution_harness.registry import build_all_registries
    from evolution_harness.resolver import resolve_design_context

    root, project = _copy_repo(tmp_path)
    source = _relocate_external_pack_to_controlled_clone(root, tmp_path)
    binding_path = project / ".agent-evolution/capabilities.yaml"
    binding = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
    binding["capabilities"].append(EXTERNAL_CAPABILITY_ID)
    binding_path.write_text(
        yaml.safe_dump(binding, sort_keys=False), encoding="utf-8"
    )

    build_all_registries(root, write=True)
    build_all_catalogs(root, write=True)
    for integration in sorted((root / "integrations").glob("*/control-plane")):
        build_capability_lock(root, integration, write=True)
    build_capability_lock(root, project, write=True)
    for runtime in ("CHATGPT", "CODEX"):
        resolved = resolve_design_context(
            root,
            project,
            intent="visual-reference-review",
            topic="web-fidelity",
            requested_output="review findings",
            runtime=runtime,
        )
        build_projection_pack(root, project, resolved, runtime=runtime)

    registry_path = root / "generated/registries/design-registry.json"
    registry_path.write_bytes(registry_path.read_bytes() + b"manual drift\n")
    expected_issues = [
        {
            "code": "GENERATED_DRIFT",
            "message": f"generated artifact drift: {registry_path}",
            "path": str(registry_path),
        }
    ]
    expected_report = {
        "schemaVersion": "structural-validation-report/v1",
        "structuralGate": "FAIL",
        "semanticGate": "NOT_ASSERTED_BY_CI",
        "issues": expected_issues,
        "capabilityCount": 10,
        "experienceCount": 3,
        "candidateCount": 2,
        "evalCount": 7,
        "integrationCount": 3,
    }
    expected_bytes = json.dumps(
        expected_report,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    repository_bytes = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    source_status = subprocess.run(
        ["git", "status", "--short"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    real_gate = capability_pack_registry._run_candidate_gate
    gate_count = 0

    def counted_gate(*args, **kwargs):
        nonlocal gate_count
        gate_count += 1
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", counted_gate)
    report = structural_validate(
        root,
        project_roots=[project],
        check_generated=True,
    )

    assert gate_count == 1
    assert report["schemaVersion"] == "structural-validation-report/v1"
    assert "verificationStats" not in report
    assert list(report) == [
        "schemaVersion",
        "structuralGate",
        "semanticGate",
        "issues",
        "capabilityCount",
        "experienceCount",
        "candidateCount",
        "evalCount",
        "integrationCount",
    ]
    assert report["issues"] == expected_issues
    assert json.dumps(
        report,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8") == expected_bytes
    assert {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    } == repository_bytes
    assert subprocess.run(
        ["git", "status", "--short"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout == source_status


def test_validate_cli_returns_structural_report_when_registration_source_is_missing(
    tmp_path: Path,
):
    root, project = _copy_repo(tmp_path)
    registration_path = root / "core/registries/capability-packs.yaml"
    registration_path.unlink()
    message = "capability pack registry source is unavailable or invalid"
    expected_report = {
        "schemaVersion": "structural-validation-report/v1",
        "structuralGate": "FAIL",
        "semanticGate": "NOT_ASSERTED_BY_CI",
        "issues": [
            {"code": "GENERATED_CHECK_FAILED", "message": message},
            {
                "code": "INTEGRATION_INVALID",
                "message": message,
                "path": str(root / "integrations/cognitura-shadow"),
            },
        ],
        "capabilityCount": 10,
        "experienceCount": 3,
        "candidateCount": 2,
        "evalCount": 7,
        "integrationCount": 3,
    }
    expected_stdout = (
        json.dumps(
            {
                "schemaVersion": "harness-cli/v1",
                "ok": False,
                "command": "validate",
                "data": expected_report,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )

    result = _run_module(
        root,
        "evolution_harness.cli",
        "validate",
        "--check-generated",
        "--format",
        "json",
    )

    assert result.returncode == 1
    assert result.stdout == expected_stdout
    assert result.stderr == ""
    assert json.loads(result.stdout)["data"] == expected_report
    assert project == root / "examples/project-fixture"


def test_unavailable_pack_preserves_complete_legacy_report_without_session_noise(
    tmp_path: Path,
):
    from evolution_harness.assurance import structural_validate

    root, project = _copy_repo(tmp_path)
    _make_external_pack_source_unavailable(root, tmp_path)
    message = "capability pack source root is unavailable"
    expected_report = {
        "schemaVersion": "structural-validation-report/v1",
        "structuralGate": "FAIL",
        "semanticGate": "NOT_ASSERTED_BY_CI",
        "issues": [
            {"code": "GENERATED_CHECK_FAILED", "message": message},
            {
                "code": "INTEGRATION_INVALID",
                "message": message,
                "path": str(root / "integrations/cognitura-shadow"),
            },
        ],
        "capabilityCount": 10,
        "experienceCount": 3,
        "candidateCount": 2,
        "evalCount": 7,
        "integrationCount": 3,
    }

    report = structural_validate(
        root,
        project_roots=[project],
        check_generated=True,
    )

    assert json.dumps(
        report,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8") == json.dumps(
        expected_report,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert all("session is failed" not in issue["message"] for issue in report["issues"])


def test_structural_validation_accepts_complete_active_and_inactive_registry(
    tmp_path: Path,
    monkeypatch,
):
    from evolution_harness import capability_pack_registry
    from evolution_harness.assurance import structural_validate
    from evolution_harness.catalog import build_all_catalogs
    from evolution_harness.project import build_capability_lock
    from evolution_harness.registry import build_all_registries

    root, project = _copy_repo(tmp_path)
    active_source = _relocate_external_pack_to_controlled_clone(root, tmp_path)
    inactive_source = _add_inactive_external_pack(root, tmp_path)
    registries = build_all_registries(root, write=True)
    build_all_catalogs(root, write=True)
    for integration in sorted((root / "integrations").glob("*/control-plane")):
        build_capability_lock(root, integration, write=True)
    build_capability_lock(root, project, write=True)
    expected_registry_bytes = (
        root / "generated/registries/capability-pack-registry.json"
    ).read_bytes()
    assert [
        (entry["registrationId"], entry["status"])
        for entry in registries["capabilityPacks"]["entries"]
    ] == [
        ("pack:inactive-pack", "INACTIVE"),
        ("pack:web-high-fidelity", "ACTIVE"),
    ]

    real_gate = capability_pack_registry._run_candidate_gate
    gate_count = 0

    def counted_gate(*args, **kwargs):
        nonlocal gate_count
        gate_count += 1
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", counted_gate)
    report = structural_validate(
        root,
        project_roots=[project],
        check_generated=True,
    )

    expected_report = {
        "schemaVersion": "structural-validation-report/v1",
        "structuralGate": "PASS",
        "semanticGate": "NOT_ASSERTED_BY_CI",
        "issues": [],
        "capabilityCount": 10,
        "experienceCount": 3,
        "candidateCount": 2,
        "evalCount": 7,
        "integrationCount": 3,
    }
    assert gate_count == 2
    assert json.dumps(
        report,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8") == json.dumps(
        expected_report,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert (
        root / "generated/registries/capability-pack-registry.json"
    ).read_bytes() == expected_registry_bytes
    for source in (active_source, inactive_source):
        assert subprocess.run(
            ["git", "status", "--short"],
            cwd=source,
            check=True,
            capture_output=True,
            text=True,
        ).stdout == ""


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


def _toolchain_bind_arguments(harness) -> list[str]:
    arguments: list[str] = []
    for name, path in harness.explicit_bindings.items():
        arguments.extend(["--bind", f"{name}={path}"])
    return arguments


def test_toolchain_provision_dry_run_performs_no_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    harness = make_provision_harness(tmp_path)
    monkeypatch.setattr(
        "evolution_harness.toolchain_provisioning.urlopen",
        lambda *_args, **_kwargs: pytest.fail("network used"),
    )

    result = main(
        [
            "--repository-root",
            str(harness.root),
            "toolchain",
            "provision",
            "--profile",
            harness.profile_id,
            *_toolchain_bind_arguments(harness),
            "--format",
            "json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["schemaVersion"] == "harness-cli/v1"
    assert payload["command"] == "toolchain provision"
    assert payload["data"]["apply"] is False
    assert not harness.binding_path.exists()
    assert not harness.published_root.exists()


def test_toolchain_provision_apply_uses_offline_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    harness = make_provision_harness(tmp_path)
    monkeypatch.setattr(
        "evolution_harness.toolchain_provisioning.urlopen",
        lambda *_args, **_kwargs: pytest.fail("network used"),
    )

    result = main(
        [
            "--repository-root",
            str(harness.root),
            "toolchain",
            "provision",
            "--profile",
            harness.profile_id,
            "--archive",
            str(harness.archive_path),
            *_toolchain_bind_arguments(harness),
            "--apply",
            "--format",
            "json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["ok"] is True
    assert payload["data"]["apply"] is True
    assert harness.binding_path.is_file()
    assert harness.published_root.is_dir()


@pytest.mark.parametrize("output_format", ["json", "text"])
def test_toolchain_status_reports_verified_after_full_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
):
    harness = make_provision_harness(tmp_path)
    monkeypatch.setattr(
        "evolution_harness.toolchain_provisioning.urlopen",
        lambda *_args, **_kwargs: pytest.fail("network used"),
    )
    apply_result = main(
        [
            "--repository-root",
            str(harness.root),
            "toolchain",
            "provision",
            "--profile",
            harness.profile_id,
            "--archive",
            str(harness.archive_path),
            *_toolchain_bind_arguments(harness),
            "--apply",
            "--format",
            "json",
        ]
    )
    apply_payload = json.loads(capsys.readouterr().out)
    assert apply_result == 0
    assert apply_payload["data"]["apply"] is True

    result = main(
        [
            "--repository-root",
            str(harness.root),
            "toolchain",
            "status",
            "--profile",
            harness.profile_id,
            "--format",
            output_format,
        ]
    )

    output = capsys.readouterr().out
    if output_format == "json":
        payload = json.loads(output)
        assert payload["schemaVersion"] == "harness-cli/v1"
        assert payload["command"] == "toolchain status"
        assert payload["ok"] is True
        status = payload["data"]["status"]
    else:
        status = yaml.safe_load(output)["status"]
    assert result == 0
    assert status == "VERIFIED"


def test_toolchain_status_missing_binding_is_deterministic_and_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    harness = make_provision_harness(tmp_path)
    monkeypatch.setattr(
        "evolution_harness.toolchain_provisioning.urlopen",
        lambda *_args, **_kwargs: pytest.fail("network used"),
    )

    result = main(
        [
            "--repository-root",
            str(harness.root),
            "toolchain",
            "status",
            "--profile",
            harness.profile_id,
            "--format",
            "json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["data"]["status"] == "MISSING"
    assert (
        "harness toolchain provision --profile "
        "toolchain-profile:test:darwin-arm64:v1 --apply"
    ) in payload["data"]["message"]


@pytest.mark.parametrize(
    ("bindings", "message"),
    [
        (["ruby=/absolute/ruby", "ruby=/absolute/other"], "duplicate toolchain binding"),
        (["unknown=/absolute/value"], "unknown toolchain binding"),
        (["ruby=relative/ruby"], "toolchain binding path must be absolute"),
        (["ruby"], "toolchain binding must use NAME=ABSOLUTE_PATH"),
    ],
)
def test_toolchain_provision_rejects_invalid_bindings(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bindings: list[str],
    message: str,
):
    harness = make_provision_harness(tmp_path)
    arguments = [
        "--repository-root",
        str(harness.root),
        "toolchain",
        "provision",
        "--profile",
        harness.profile_id,
    ]
    for binding in bindings:
        arguments.extend(["--bind", binding])
    arguments.extend(["--format", "json"])

    result = main(arguments)

    payload = json.loads(capsys.readouterr().out)
    assert result == 1
    assert payload["schemaVersion"] == "harness-cli/v1"
    assert payload["ok"] is False
    assert message in payload["data"]["message"]
