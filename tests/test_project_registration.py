from __future__ import annotations

import shutil
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from capability_pack_test_support import retain_web_registration_fixture


NEUTRAL_LOCK = "sha256:6e18d9cd91420d5529f0679cbf1d1cad7be5ae6a76b10df16ebed0d6a5004c24"


def _registration(**overrides: str) -> dict[str, str]:
    value = {
        "schemaVersion": "project-harness-registration/v1",
        "harnessId": "agent-evolution-harness",
        "integrationId": "neutral-shadow",
        "integrationPath": "integrations/neutral-shadow",
        "sourceRoot": "SELF",
        "sourceAccess": "READ_ONLY",
        "runtime": "CODEX",
        "capabilityLockFingerprint": NEUTRAL_LOCK,
    }
    value.update(overrides)
    return value


def _write_registration(source: Path, value: dict[str, str] | None = None) -> Path:
    path = source / ".agent-evolution/registration.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value or _registration(), sort_keys=False), encoding="utf-8")
    return path


def _source_fixture(tmp_path: Path) -> Path:
    repository = Path(__file__).parents[1]
    source = tmp_path / "external-project"
    shutil.copytree(repository / "examples/external-project-source", source)
    return source


def _harness_fixture(tmp_path: Path) -> Path:
    repository = Path(__file__).parents[1]
    root = tmp_path / "harness"
    for name in ["core", "design", "runtime"]:
        shutil.copytree(repository / name, root / name)
    (root / "integrations").mkdir()
    shutil.copytree(repository / "integrations/neutral-shadow", root / "integrations/neutral-shadow")
    return root


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
        capture_output=True,
        text=True,
        env=environment,
    )


def _invoke_cli(capsys: pytest.CaptureFixture[str], root: Path, *args: str) -> tuple[int, str, str]:
    from evolution_harness import cli

    return_code = cli.main(["--repository-root", str(root), *args])
    captured = capsys.readouterr()
    return return_code, captured.out, captured.err


def _external_registered_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    from evolution_harness.project import build_capability_lock

    root = _harness_fixture(tmp_path)
    retain_web_registration_fixture(root)
    registry_path = root / "core/registries/capability-packs.yaml"
    registrations = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    pack = tmp_path / "external-pack"
    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "--no-hardlinks",
            registrations[0]["source"]["repositoryPath"],
            str(pack),
        ],
        check=True,
        capture_output=True,
    )
    registrations[0]["source"]["repositoryPath"] = str(pack)
    registry_path.write_text(
        yaml.safe_dump(registrations, sort_keys=False), encoding="utf-8"
    )
    schema_path = root / "core/schemas/capability-pack-registration.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["properties"]["source"]["properties"]["repositoryPath"]["const"] = str(
        pack
    )
    schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

    integration = root / "integrations/neutral-shadow"
    control = integration / "control-plane"
    binding_path = control / ".agent-evolution/capabilities.yaml"
    binding = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
    binding["capabilities"].append(
        "workflow:web-high-fidelity:reference-driven-visual-fidelity"
    )
    binding_path.write_text(
        yaml.safe_dump(binding, sort_keys=False), encoding="utf-8"
    )
    lock = build_capability_lock(root, control, write=True)
    source = _source_fixture(tmp_path)
    _write_registration(
        source,
        _registration(capabilityLockFingerprint=lock["lockFingerprint"]),
    )
    return root, integration, source


def test_load_project_registration_resolves_valid_registered_integration(tmp_path: Path):
    from evolution_harness.registration import load_project_registration

    repository = Path(__file__).parents[1]
    source = _source_fixture(tmp_path)
    registration_path = _write_registration(source)

    loaded = load_project_registration(repository, source)

    assert loaded["registrationPath"] == registration_path
    assert loaded["sourceRoot"] == source
    assert loaded["integrationRoot"] == repository / "integrations/neutral-shadow"
    assert loaded["registration"] == _registration()
    assert loaded["integration"]["config"]["id"] == "neutral-shadow"


@pytest.mark.parametrize("integration_path", ["../neutral-shadow", "/tmp/neutral-shadow"])
def test_load_project_registration_rejects_unsafe_integration_path(
    tmp_path: Path, integration_path: str
):
    from evolution_harness.registration import ProjectRegistrationError, load_project_registration

    repository = Path(__file__).parents[1]
    source = _source_fixture(tmp_path)
    _write_registration(source, _registration(integrationPath=integration_path))

    with pytest.raises(ProjectRegistrationError, match="unsafe integration path"):
        load_project_registration(repository, source)


def test_load_project_registration_rejects_registration_symlink(tmp_path: Path):
    from evolution_harness.registration import ProjectRegistrationError, load_project_registration

    repository = Path(__file__).parents[1]
    source = _source_fixture(tmp_path)
    external = tmp_path / "registration.yaml"
    external.write_text(yaml.safe_dump(_registration(), sort_keys=False), encoding="utf-8")
    registration_path = source / ".agent-evolution/registration.yaml"
    registration_path.unlink()
    registration_path.symlink_to(external)

    with pytest.raises(ProjectRegistrationError, match="registration path contains symlink"):
        load_project_registration(repository, source)


def test_load_project_registration_rejects_project_source_symlink(tmp_path: Path):
    from evolution_harness.registration import ProjectRegistrationError, load_project_registration

    repository = Path(__file__).parents[1]
    source = _source_fixture(tmp_path)
    _write_registration(source)
    source_link = tmp_path / "external-project-link"
    source_link.symlink_to(source, target_is_directory=True)

    with pytest.raises(ProjectRegistrationError, match="project source root must not be a symlink"):
        load_project_registration(repository, source_link)


def test_load_project_registration_rejects_integration_symlink(tmp_path: Path):
    from evolution_harness.registration import ProjectRegistrationError, load_project_registration

    repository = Path(__file__).parents[1]
    root = _harness_fixture(tmp_path)
    real_integration = root / "real-neutral-shadow"
    (root / "integrations/neutral-shadow").rename(real_integration)
    (root / "integrations/neutral-shadow").symlink_to(real_integration, target_is_directory=True)
    source = _source_fixture(tmp_path)
    _write_registration(source)

    with pytest.raises(ProjectRegistrationError, match="integration path contains symlink"):
        load_project_registration(root, source)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"harnessId": "different-harness"}, "harness identity mismatch"),
        ({"integrationId": "different-integration"}, "integration identity mismatch"),
        ({"runtime": "CHATGPT"}, "integration runtime mismatch"),
        ({"sourceAccess": "WRITE"}, "registration schema is invalid"),
        ({"sourceRoot": "../source"}, "registration schema is invalid"),
        ({"currentStage": "REPOSITORY_LANDING"}, "registration schema is invalid"),
        (
            {"capabilityLockFingerprint": "sha256:" + "0" * 64},
            "capability lock fingerprint mismatch",
        ),
    ],
)
def test_load_project_registration_rejects_identity_runtime_access_and_lock_drift(
    tmp_path: Path, overrides: dict[str, str], message: str
):
    from evolution_harness.registration import ProjectRegistrationError, load_project_registration

    repository = Path(__file__).parents[1]
    source = _source_fixture(tmp_path)
    _write_registration(source, _registration(**overrides))

    with pytest.raises(ProjectRegistrationError, match=message):
        load_project_registration(repository, source)


def test_registration_check_cli_reports_validated_read_only_binding(tmp_path: Path):
    repository = Path(__file__).parents[1]
    source = _source_fixture(tmp_path)
    _write_registration(source)

    result = _run_cli(
        repository,
        "integration",
        "registration-check",
        "--source",
        str(source),
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"] == {
        "schemaVersion": "project-registration-check/v1",
        "gate": "PASS",
        "harnessId": "agent-evolution-harness",
        "integrationId": "neutral-shadow",
        "integrationPath": "integrations/neutral-shadow",
        "runtime": "CODEX",
        "sourceAccess": "READ_ONLY",
        "capabilityLockFingerprint": NEUTRAL_LOCK,
    }


def test_registered_cli_discovery_matches_explicit_inspect_resolve_and_projection(
    tmp_path: Path,
):
    from evolution_harness.integration import build_integration_projection

    root = _harness_fixture(tmp_path)
    integration = root / "integrations/neutral-shadow"
    source = _source_fixture(tmp_path)
    _write_registration(source)
    request = [
        "--source",
        str(source),
        "--intent",
        "architecture-review",
        "--topic",
        "runtime-integration",
        "--output",
        "review findings",
        "--runtime",
        "CODEX",
        "--format",
        "json",
    ]

    explicit_inspect = _run_cli(
        root,
        "integration",
        "inspect",
        "--integration",
        str(integration),
        "--source",
        str(source),
        "--format",
        "json",
    )
    discovered_inspect = _run_cli(
        root,
        "integration",
        "inspect",
        "--source",
        str(source),
        "--format",
        "json",
    )
    assert explicit_inspect.returncode == discovered_inspect.returncode == 0
    assert json.loads(explicit_inspect.stdout)["data"] == json.loads(discovered_inspect.stdout)["data"]

    explicit_resolution = _run_cli(
        root,
        "integration",
        "resolve",
        "--integration",
        str(integration),
        *request,
    )
    discovered_resolution = _run_cli(root, "integration", "resolve", *request)
    assert explicit_resolution.returncode == discovered_resolution.returncode == 0
    assert json.loads(explicit_resolution.stdout)["data"]["resolutionId"] == json.loads(
        discovered_resolution.stdout
    )["data"]["resolutionId"]

    build_integration_projection(
        root,
        integration,
        source,
        intent="architecture-review",
        topic="runtime-integration",
        requested_output="review findings",
        runtime="CODEX",
    )
    discovered_projection = _run_cli(root, "integration", "projection", *request[:-2], "--check", "--format", "json")
    assert discovered_projection.returncode == 0, discovered_projection.stdout
    assert json.loads(discovered_projection.stdout)["data"] == {"fresh": True, "reasons": []}


@pytest.mark.parametrize(
    ("action", "operation_args", "prepare_projection"),
    [
        ("inspect", (), False),
        (
            "resolve",
            (
                "--intent",
                "architecture-review",
                "--topic",
                "runtime-integration",
                "--output",
                "review findings",
                "--runtime",
                "CODEX",
            ),
            False,
        ),
        (
            "projection",
            (
                "--intent",
                "architecture-review",
                "--topic",
                "runtime-integration",
                "--output",
                "review findings",
                "--runtime",
                "CODEX",
            ),
            False,
        ),
        (
            "projection",
            (
                "--intent",
                "architecture-review",
                "--topic",
                "runtime-integration",
                "--output",
                "review findings",
                "--runtime",
                "CODEX",
                "--check",
            ),
            True,
        ),
    ],
    ids=("inspect", "resolve", "projection-build", "projection-check"),
)
def test_registered_cli_operation_owns_one_gate_without_output_or_exit_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    action: str,
    operation_args: tuple[str, ...],
    prepare_projection: bool,
):
    from evolution_harness import capability_pack_registry
    from evolution_harness.integration import build_integration_projection

    root, integration, source = _external_registered_fixture(tmp_path)
    registration_path = source / ".agent-evolution/registration.yaml"
    registration_bytes = registration_path.read_bytes()
    if prepare_projection:
        build_integration_projection(
            root,
            integration,
            source,
            intent="architecture-review",
            topic="runtime-integration",
            requested_output="review findings",
            runtime="CODEX",
        )

    registration_path.unlink()
    expected = _invoke_cli(
        capsys,
        root,
        "integration",
        action,
        "--integration",
        str(integration),
        "--source",
        str(source),
        *operation_args,
        "--format",
        "json",
    )
    registration_path.write_bytes(registration_bytes)

    real_gate = capability_pack_registry._run_candidate_gate
    gate_count = 0

    def counted_gate(*args, **kwargs):
        nonlocal gate_count
        gate_count += 1
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", counted_gate)
    actual = _invoke_cli(
        capsys,
        root,
        "integration",
        action,
        "--source",
        str(source),
        *operation_args,
        "--format",
        "json",
    )

    assert actual == expected
    assert actual[0] == 0
    assert gate_count == 1


def test_registered_cli_fails_closed_when_lock_drifts_between_bootstrap_and_live_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    from evolution_harness import registration

    root, _, source = _external_registered_fixture(tmp_path)
    real_bootstrap = registration._bootstrap_registered_integration

    def drifting_bootstrap(*args, **kwargs):
        bootstrap = real_bootstrap(*args, **kwargs)
        lock_path = bootstrap.control_plane_root / ".agent-evolution/capabilities.lock.yaml"
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
        lock["lockFingerprint"] = "sha256:" + "0" * 64
        lock_path.write_text(
            yaml.safe_dump(lock, sort_keys=False), encoding="utf-8"
        )
        return bootstrap

    monkeypatch.setattr(
        registration, "_bootstrap_registered_integration", drifting_bootstrap
    )
    result = _invoke_cli(
        capsys,
        root,
        "integration",
        "inspect",
        "--source",
        str(source),
        "--format",
        "json",
    )

    assert result == (
        1,
        json.dumps(
            {
                "schemaVersion": "harness-cli/v1",
                "ok": False,
                "command": "integration inspect",
                "data": {
                    "code": "INTERNAL_ERROR",
                    "message": "registered capability lock is invalid: capability lock fingerprint mismatch",
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        "",
    )


@pytest.mark.parametrize(
    ("mutation", "expected_gate_count"),
    [("external-removal", 0), ("same-id-lock-replacement", 1)],
)
def test_registered_cli_fails_closed_on_structurally_valid_bootstrap_live_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mutation: str,
    expected_gate_count: int,
):
    from evolution_harness import capability_pack_registry, registration
    from evolution_harness.project import (
        build_capability_lock,
        capability_lock_fingerprint,
    )

    root, _, source = _external_registered_fixture(tmp_path)
    real_bootstrap = registration._bootstrap_registered_integration
    real_gate = capability_pack_registry._run_candidate_gate
    gate_count = 0
    mutated = False

    def counted_gate(*args, **kwargs):
        nonlocal gate_count
        gate_count += 1
        return real_gate(*args, **kwargs)

    def coordinated_drift(*args, **kwargs):
        nonlocal mutated
        bootstrap = real_bootstrap(*args, **kwargs)
        if mutated:
            return bootstrap
        mutated = True
        binding_path = (
            bootstrap.control_plane_root / ".agent-evolution/capabilities.yaml"
        )
        binding = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
        capability_id = "workflow:web-high-fidelity:reference-driven-visual-fidelity"
        binding["capabilities"].remove(capability_id)
        if mutation == "same-id-lock-replacement":
            binding["extensions"].append(capability_id)
        binding_path.write_text(
            yaml.safe_dump(binding, sort_keys=False), encoding="utf-8"
        )

        if mutation == "external-removal":
            lock = build_capability_lock(
                bootstrap.repository_root,
                bootstrap.control_plane_root,
                write=True,
            )
        else:
            lock_path = (
                bootstrap.control_plane_root
                / ".agent-evolution/capabilities.lock.yaml"
            )
            lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            external = next(
                item
                for item in lock["capabilities"]
                if item["capabilityId"] == capability_id
            )
            external["resolvedBecause"] = ["project-extension"]
            lock["lockFingerprint"] = capability_lock_fingerprint(lock)
            lock_path.write_text(
                yaml.safe_dump(lock, sort_keys=False), encoding="utf-8"
            )

        registration_path = source / ".agent-evolution/registration.yaml"
        registration_value = yaml.safe_load(
            registration_path.read_text(encoding="utf-8")
        )
        registration_value["capabilityLockFingerprint"] = lock["lockFingerprint"]
        registration_path.write_text(
            yaml.safe_dump(registration_value, sort_keys=False), encoding="utf-8"
        )
        return bootstrap

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", counted_gate)
    monkeypatch.setattr(
        registration, "_bootstrap_registered_integration", coordinated_drift
    )
    result = _invoke_cli(
        capsys,
        root,
        "integration",
        "inspect",
        "--source",
        str(source),
        "--format",
        "json",
    )

    assert result == (
        1,
        json.dumps(
            {
                "schemaVersion": "harness-cli/v1",
                "ok": False,
                "command": "integration inspect",
                "data": {
                    "code": "INTERNAL_ERROR",
                    "message": "project registration structural witness changed during verification",
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        "",
    )
    assert gate_count == expected_gate_count


def test_registration_check_cli_fails_closed_on_valid_external_removal_aba(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    from evolution_harness import capability_pack_registry, registration
    from evolution_harness.project import build_capability_lock

    root, _, source = _external_registered_fixture(tmp_path)
    real_bootstrap = registration._bootstrap_registered_integration
    real_gate = capability_pack_registry._run_candidate_gate
    registration_path = source / ".agent-evolution/registration.yaml"
    control = root / "integrations/neutral-shadow/control-plane"
    binding_path = control / ".agent-evolution/capabilities.yaml"
    lock_path = control / ".agent-evolution/capabilities.lock.yaml"
    original_bytes = {
        registration_path: registration_path.read_bytes(),
        binding_path: binding_path.read_bytes(),
        lock_path: lock_path.read_bytes(),
    }
    gate_count = 0
    bootstrap_count = 0

    def counted_gate(*args, **kwargs):
        nonlocal gate_count
        gate_count += 1
        return real_gate(*args, **kwargs)

    def aba_bootstrap(*args, **kwargs):
        nonlocal bootstrap_count
        bootstrap_count += 1
        if bootstrap_count == 1:
            initial = real_bootstrap(*args, **kwargs)
            binding = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
            binding["capabilities"].remove(
                "workflow:web-high-fidelity:reference-driven-visual-fidelity"
            )
            binding_path.write_text(
                yaml.safe_dump(binding, sort_keys=False), encoding="utf-8"
            )
            live_lock = build_capability_lock(root, control, write=True)
            registration_value = yaml.safe_load(
                registration_path.read_text(encoding="utf-8")
            )
            registration_value["capabilityLockFingerprint"] = live_lock[
                "lockFingerprint"
            ]
            registration_path.write_text(
                yaml.safe_dump(registration_value, sort_keys=False),
                encoding="utf-8",
            )
            return initial
        for path, data in original_bytes.items():
            path.write_bytes(data)
        return real_bootstrap(*args, **kwargs)

    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", counted_gate)
    monkeypatch.setattr(
        registration, "_bootstrap_registered_integration", aba_bootstrap
    )
    result = _invoke_cli(
        capsys,
        root,
        "integration",
        "registration-check",
        "--source",
        str(source),
        "--format",
        "json",
    )

    assert result == (
        1,
        json.dumps(
            {
                "schemaVersion": "harness-cli/v1",
                "ok": False,
                "command": "integration registration-check",
                "data": {
                    "code": "INTERNAL_ERROR",
                    "message": "project registration structural witness changed during verification",
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        "",
    )
    assert gate_count == 0
    assert bootstrap_count == 2
    assert all(path.read_bytes() == data for path, data in original_bytes.items())


def test_registered_cli_discovery_requires_registration_without_explicit_integration(tmp_path: Path):
    repository = Path(__file__).parents[1]
    source = _source_fixture(tmp_path)
    (source / ".agent-evolution/registration.yaml").unlink()

    result = _run_cli(
        repository,
        "integration",
        "inspect",
        "--source",
        str(source),
        "--format",
        "json",
    )

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "registration" in payload["data"]["message"]


def test_registered_cli_discovery_rejects_explicit_integration_disagreement(tmp_path: Path):
    repository = Path(__file__).parents[1]
    source = _source_fixture(tmp_path)
    _write_registration(source)

    result = _run_cli(
        repository,
        "integration",
        "inspect",
        "--integration",
        str(repository / "integrations/neutral-shadow/control-plane"),
        "--source",
        str(source),
        "--format",
        "json",
    )

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["data"]["message"] == "explicit integration disagrees with project registration"


def test_registered_cli_discovery_preserves_closed_topic_authority_reconciliation(tmp_path: Path):
    repository = Path(__file__).parents[1]
    source = _source_fixture(tmp_path)
    decisions = source / "decisions.md"
    decisions.write_text(
        decisions.read_text(encoding="utf-8").replace("ApiBoundaryStatus = CLOSED", "ApiBoundaryStatus = OPEN"),
        encoding="utf-8",
    )

    result = _run_cli(
        repository,
        "integration",
        "resolve",
        "--source",
        str(source),
        "--intent",
        "architecture-review",
        "--topic",
        "api-boundary",
        "--output",
        "review findings",
        "--runtime",
        "CODEX",
        "--format",
        "json",
    )

    assert result.returncode == 1, result.stderr
    assert "topic status authority mismatch" in json.loads(result.stdout)["data"]["message"]


def test_registered_cli_projection_check_rejects_live_authority_drift(tmp_path: Path):
    from evolution_harness.integration import build_integration_projection

    root = _harness_fixture(tmp_path)
    integration = root / "integrations/neutral-shadow"
    source = _source_fixture(tmp_path)
    build_integration_projection(
        root,
        integration,
        source,
        intent="architecture-review",
        topic="runtime-integration",
        requested_output="review findings",
        runtime="CODEX",
    )
    status = source / "status.md"
    status.write_text(
        status.read_text(encoding="utf-8").replace(
            "DevelopmentAuthorization = NO_WINDOW_CLOSED",
            "DevelopmentAuthorization = YES_POISONED_DRIFT",
        ),
        encoding="utf-8",
    )

    result = _run_cli(
        root,
        "integration",
        "projection",
        "--source",
        str(source),
        "--intent",
        "architecture-review",
        "--topic",
        "runtime-integration",
        "--output",
        "review findings",
        "--runtime",
        "CODEX",
        "--check",
        "--format",
        "json",
    )

    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)["data"] == {"fresh": False, "reasons": ["projection-integrity-drift"]}


def test_registered_cli_inspect_preserves_excluded_path_rejection(tmp_path: Path):
    root = _harness_fixture(tmp_path)
    integration = root / "integrations/neutral-shadow"
    authority_path = integration / "authority-map.yaml"
    authority_map = yaml.safe_load(authority_path.read_text(encoding="utf-8"))
    authority_map["authorities"].append(
        {
            "id": "poisoned-secret",
            "path": "private/secret.md",
            "format": "MARKDOWN_KV",
            "role": "CANONICAL",
            "required": True,
            "owns": ["secret.value"],
            "selectors": {"secret.value": {"key": "Secret", "required": True}},
        }
    )
    authority_path.write_text(yaml.safe_dump(authority_map, sort_keys=False), encoding="utf-8")
    source = _source_fixture(tmp_path)

    result = _run_cli(
        root,
        "integration",
        "inspect",
        "--source",
        str(source),
        "--format",
        "json",
    )

    assert result.returncode == 1, result.stderr
    assert "authority path is excluded" in json.loads(result.stdout)["data"]["message"]


def test_cognitura_registration_pointer_accepts_only_exact_read_only_sidecar_lock(
    tmp_path: Path,
):
    from evolution_harness.project import load_capability_lock
    from evolution_harness.registration import load_project_registration

    repository = Path(__file__).parents[1]
    source = tmp_path / "cognitura-source"
    source.mkdir()
    lock = load_capability_lock(
        repository,
        repository / "integrations/cognitura-shadow/control-plane",
    )
    registration = {
        "schemaVersion": "project-harness-registration/v1",
        "harnessId": "agent-evolution-harness",
        "integrationId": "cognitura-shadow",
        "integrationPath": "integrations/cognitura-shadow",
        "sourceRoot": "SELF",
        "sourceAccess": "READ_ONLY",
        "runtime": "CODEX",
        "capabilityLockFingerprint": lock["lockFingerprint"],
    }
    _write_registration(source, registration)

    loaded = load_project_registration(repository, source)

    assert loaded["integrationRoot"] == repository / "integrations/cognitura-shadow"
    assert loaded["registration"]["capabilityLockFingerprint"] == lock["lockFingerprint"]
    assert loaded["integration"]["config"]["sourceAccess"] == "READ_ONLY"
