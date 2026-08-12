from __future__ import annotations

import shutil
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


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
