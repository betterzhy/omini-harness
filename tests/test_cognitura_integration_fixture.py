from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from capability_pack_test_support import retain_web_registration_fixture


WEB_CAPABILITY_ID = "workflow:web-high-fidelity:reference-driven-visual-fidelity"
COGNITURA_SOURCE_REPOSITORY = Path("/Users/yuzhuangzhuang/Projects/cognitura")
COGNITURA_SOURCE_COMMIT = "a14206d5171b776b6fe14dbb0feca582d982a393"


def _write_source_authority(source: Path) -> None:
    wave2_index = source / "docs/task-cards/wave-2/README.md"
    wave2_index.parent.mkdir(parents=True, exist_ok=True)
    wave2_index.write_text(
        """# Cognitura Wave 2 设计任务卡索引

```text
TaskCardSetStatus = READY_FOR_EXECUTION
ActiveTaskCard = W2-D05
Wave2BusinessImplementation = NOT_AUTHORIZED
```

本卡集只授权书面设计治理，不授权任何业务实现或页面实现。
""",
        encoding="utf-8",
    )
    legacy_binding = source / "docs/engineering/cognitura-high-fidelity-harness-binding.md"
    legacy_binding.parent.mkdir(parents=True, exist_ok=True)
    legacy_binding.write_text(
        """# Cognitura High-Fidelity Harness Binding

```text
REAL_PAGE_PILOT=NOT_AUTHORIZED
```
""",
        encoding="utf-8",
    )
    idea = source / ".idea/workspace.xml"
    idea.parent.mkdir(parents=True, exist_ok=True)
    idea.write_text("must-not-be-read\n", encoding="utf-8")

    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(
        ["git", "-C", str(source), "add", "docs"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Cognitura Fixture",
            "-c",
            "user.email=cognitura-fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )


def _copy_harness_fixture(tmp_path: Path) -> Path:
    repository = Path(__file__).parents[1]
    root = tmp_path / "harness"
    for name in ["core", "design", "runtime"]:
        shutil.copytree(repository / name, root / name)
    retain_web_registration_fixture(root)
    integration = root / "integrations/cognitura-shadow"
    shutil.copytree(repository / "integrations/cognitura-shadow", integration)
    return root


def _copy_cognitura_shadow_fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = _copy_harness_fixture(tmp_path)
    source = tmp_path / "cognitura-source"
    source.mkdir()
    _write_source_authority(source)
    return root, source


def _clone_real_cognitura_source(tmp_path: Path) -> Path:
    source = tmp_path / "real-cognitura-source"
    subprocess.run(
        [
            "git",
            "clone",
            "--shared",
            "--dissociate",
            "--no-checkout",
            "-q",
            str(COGNITURA_SOURCE_REPOSITORY),
            str(source),
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "checkout", "-q", "--detach", COGNITURA_SOURCE_COMMIT],
        check=True,
    )
    assert subprocess.run(
        ["git", "-C", str(source), "status", "--porcelain=v1", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout == ""
    assert not (source / ".git/objects/info/alternates").exists()
    return source


def _run_scenario(tmp_path: Path, name: str) -> dict[str, object]:
    from evolution_harness.scenario import run_integration_scenario

    root, source = _copy_cognitura_shadow_fixture(tmp_path)
    integration = root / "integrations/cognitura-shadow"
    result = run_integration_scenario(
        root,
        integration,
        source,
        integration / f"scenarios/{name}.yaml",
    )
    assert result["gate"] == "PASS", result["checks"]
    checks = {item["name"]: item["actual"] for item in result["checks"]}
    return {
        "authorityGate": checks["authority-gate"],
        "facts": {
            key.removeprefix("fact:"): value
            for key, value in checks.items()
            if key.startswith("fact:")
        },
        "conflictResolutionRules": checks["conflict-resolution-rules"],
    }


def test_cognitura_shadow_is_read_only_and_locks_web_pack(tmp_path: Path):
    from evolution_harness.authority import build_authority_snapshot
    from evolution_harness.integration import load_integration
    from evolution_harness.project import load_capability_lock

    root, source = _copy_cognitura_shadow_fixture(tmp_path)
    integration = root / "integrations/cognitura-shadow"
    loaded = load_integration(root, integration)

    assert loaded["config"]["sourceAccess"] == "READ_ONLY"
    assert loaded["config"]["runtime"] == "CODEX"
    assert ".idea/**" in loaded["config"]["excludedPaths"]
    snapshot = build_authority_snapshot(root, integration, source)
    assert snapshot["gate"] == "PASS"
    assert snapshot["sourceRevision"]["authoritySetStatus"] == "CLEAN_FOR_AUTHORITY_SET"
    assert {item["path"] for item in snapshot["authorities"]} == {
        "docs/task-cards/wave-2/README.md",
        "docs/engineering/cognitura-high-fidelity-harness-binding.md",
    }

    lock = load_capability_lock(root, loaded["controlPlaneRoot"])
    assert lock["schemaVersion"] == "capability-lock/v2"
    assert [item["capabilityId"] for item in lock["capabilities"]] == [WEB_CAPABILITY_ID]


def test_cognitura_shadow_cannot_turn_pack_result_into_page_authorization(tmp_path: Path):
    result = _run_scenario(tmp_path, "unauthorized-page-completion")

    assert result["authorityGate"] == "PASS"
    assert result["facts"]["permission.page-implementation"] == "DENY"
    assert result["facts"]["permission.real-page-pilot"] == "DENY"
    assert "PROJECT_TRUTH_WINS" in result["conflictResolutionRules"]


def test_cognitura_business_authority_does_not_imply_page_authorization(tmp_path: Path):
    from evolution_harness.integration import resolve_integration_context

    root, source = _copy_cognitura_shadow_fixture(tmp_path)
    wave2_index = source / "docs/task-cards/wave-2/README.md"
    wave2_index.write_text(
        wave2_index.read_text(encoding="utf-8").replace(
            "Wave2BusinessImplementation = NOT_AUTHORIZED",
            "Wave2BusinessImplementation = AUTHORIZED",
        ),
        encoding="utf-8",
    )

    resolved = resolve_integration_context(
        root,
        root / "integrations/cognitura-shadow",
        source,
        intent="visual-review",
        topic="web-pack-adoption-preparation",
        requested_output="read-only review findings",
        runtime="CODEX",
    )

    assert resolved["authorityFacts"]["permission.business-implementation"][
        "normalizedValue"
    ] == "ALLOW"
    assert resolved["authorityFacts"]["permission.page-implementation"][
        "normalizedValue"
    ] != "ALLOW"


@pytest.mark.parametrize("legacy_value", ["AUTHORIZED", "UNRECOGNIZED_VALUE"])
def test_real_cognitura_legacy_pilot_mutation_fails_closed(
    tmp_path: Path,
    legacy_value: str,
):
    from evolution_harness.scenario import run_integration_scenario

    root = _copy_harness_fixture(tmp_path)
    source = _clone_real_cognitura_source(tmp_path)
    integration = root / "integrations/cognitura-shadow"
    legacy_binding = source / "docs/engineering/cognitura-high-fidelity-harness-binding.md"
    original = legacy_binding.read_text(encoding="utf-8")
    mutated = original.replace(
        "REAL_PAGE_PILOT=NOT_AUTHORIZED",
        f"REAL_PAGE_PILOT={legacy_value}",
    )
    assert mutated != original
    legacy_binding.write_text(mutated, encoding="utf-8")

    result = run_integration_scenario(
        root,
        integration,
        source,
        integration / "scenarios/unauthorized-page-completion.yaml",
    )
    checks = {item["name"]: item for item in result["checks"]}
    pilot = checks["fact:permission.real-page-pilot"]

    assert checks["authority-gate"]["actual"] == "PASS"
    assert result["gate"] == "NO_GO"
    assert pilot["expected"] == "DENY"
    assert pilot["actual"] == "UNKNOWN"
    assert pilot["pass"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("pack-digest", "external capability pack lock registration drift"),
        ("validator-hash", "external capability pack lock registration drift"),
        ("project-lock-fingerprint", "capability lock fingerprint mismatch"),
        ("authority-selector", "authority snapshot gate is NO_GO"),
    ],
)
def test_cognitura_shadow_identity_and_authority_drift_fail_closed(
    tmp_path: Path,
    mutation: str,
    message: str,
):
    from evolution_harness.integration import resolve_integration_context
    from evolution_harness.project import load_capability_lock, verify_capability_lock

    root, source = _copy_cognitura_shadow_fixture(tmp_path)
    integration = root / "integrations/cognitura-shadow"
    control = integration / "control-plane"

    if mutation in {"pack-digest", "validator-hash"}:
        registry_path = root / "core/registries/capability-packs.yaml"
        registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        registration = registry[0]
        if mutation == "pack-digest":
            registration["resolvedContentDigest"] = "sha256:" + "0" * 64
        else:
            registration["validator"]["sha256"] = "sha256:" + "0" * 64
        registry_path.write_text(
            yaml.safe_dump(registry, sort_keys=False),
            encoding="utf-8",
        )
        operation = lambda: verify_capability_lock(root, control)
    elif mutation == "project-lock-fingerprint":
        lock_path = control / ".agent-evolution/capabilities.lock.yaml"
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
        lock["lockFingerprint"] = "sha256:" + "0" * 64
        lock_path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")
        operation = lambda: load_capability_lock(root, control)
    else:
        authority_path = integration / "authority-map.yaml"
        authority_map = yaml.safe_load(authority_path.read_text(encoding="utf-8"))
        selector = authority_map["authorities"][0]["selectors"][
            "permission.page-implementation"
        ]
        selector["key"] = "PageImplementation"
        authority_path.write_text(
            yaml.safe_dump(authority_map, sort_keys=False),
            encoding="utf-8",
        )
        operation = lambda: resolve_integration_context(
            root,
            integration,
            source,
            intent="visual-review",
            topic="web-pack-adoption-preparation",
            requested_output="read-only review findings",
            runtime="CODEX",
        )

    with pytest.raises(ValueError, match=message):
        operation()


def test_cognitura_shadow_projection_is_verified_and_install_is_dry_run(tmp_path: Path):
    from evolution_harness.authority import build_authority_snapshot
    from evolution_harness.install import install_projection
    from evolution_harness.integration import build_integration_projection
    from evolution_harness.projection import validate_projection_pack

    root, source = _copy_cognitura_shadow_fixture(tmp_path)
    integration = root / "integrations/cognitura-shadow"
    control = integration / "control-plane"
    manifest = build_integration_projection(
        root,
        integration,
        source,
        intent="visual-review",
        topic="web-pack-adoption-preparation",
        requested_output="read-only visual review findings",
        runtime="CODEX",
    )
    pack = root / "generated/projections/codex/cognitura-shadow"
    snapshot = build_authority_snapshot(root, integration, source)
    validated, resolved = validate_projection_pack(
        root,
        control,
        pack,
        runtime="CODEX",
        authority_snapshot=snapshot,
    )

    assert validated == manifest
    assert [item["id"] for item in manifest["sourceCapabilities"]] == [WEB_CAPABILITY_ID]
    assert resolved["authorityFacts"]["permission.page-implementation"]["normalizedValue"] == "DENY"
    assert (pack / "skills/web-high-fidelity/SKILL.md").is_file()

    target = tmp_path / "disposable-cognitura-target"
    target.mkdir()
    plan = install_projection(root, pack, target, source_root=source)
    assert plan["mode"] == "DRY_RUN"
    assert plan["gate"] == "PASS"
    assert [(item["operation"], item["target"]) for item in plan["actions"]] == [
        ("CREATE", ".agents/skills/web-high-fidelity/SKILL.md")
    ]
    assert list(target.iterdir()) == []
    assert "/tmp/" not in json.dumps(manifest, sort_keys=True)
