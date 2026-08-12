from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .authority import build_authority_snapshot
from .integration import load_integration, resolve_integration_context
from .schema import SchemaStore


def run_integration_scenario(
    repository_root: Path,
    integration_root: Path,
    source_root: Path,
    scenario_path: Path,
) -> dict[str, Any]:
    repository = Path(repository_root)
    integration = Path(integration_root).resolve()
    load_integration(repository, integration)
    scenario_file = Path(scenario_path).resolve(strict=True)
    try:
        scenario_file.relative_to((integration / "scenarios").resolve())
    except ValueError as exc:
        raise ValueError("scenario file must be inside the integration scenarios directory") from exc
    scenario = yaml.safe_load(scenario_file.read_text(encoding="utf-8")) or {}
    SchemaStore(repository).validate("core/schemas/project-integration-scenario.schema.json", scenario)
    expected = scenario["expected"]
    snapshot = build_authority_snapshot(repository, integration_root, source_root)
    checks: list[dict[str, Any]] = []

    def check(name: str, actual: Any, wanted: Any) -> None:
        checks.append({"name": name, "expected": wanted, "actual": actual, "pass": actual == wanted})

    check("authority-gate", snapshot["gate"], expected["authorityGate"])
    resolved: dict[str, Any] | None = None
    if snapshot["gate"] == "PASS":
        resolved = resolve_integration_context(
            repository,
            integration_root,
            source_root,
            intent=scenario["intent"],
            topic=scenario["topic"],
            requested_output=scenario["requestedOutput"],
            runtime=scenario["runtime"],
            explicit_stage=scenario.get("explicitStage"),
            reopen_signal=scenario.get("reopenSignal"),
        )
        if "topicGuard" in expected:
            check("topic-guard", resolved["topicGuard"], expected["topicGuard"])
        for fact_id, wanted in sorted(expected.get("facts", {}).items()):
            actual = resolved["authorityFacts"].get(fact_id, {}).get("normalizedValue")
            check(f"fact:{fact_id}", actual, wanted)
        if "selectedCapabilities" in expected:
            actual = sorted(item["id"] for item in resolved["selectedCapabilities"])
            check("selected-capabilities", actual, sorted(expected["selectedCapabilities"]))
        if "excludedCapabilities" in expected:
            actual = sorted(item["id"] for item in resolved["explain"]["excluded"])
            wanted = sorted(expected["excludedCapabilities"])
            checks.append(
                {
                    "name": "excluded-capabilities",
                    "expected": wanted,
                    "actual": actual,
                    "pass": set(wanted).issubset(actual),
                }
            )
        if "conflictResolutionRules" in expected:
            actual = sorted({item["resolutionRule"] for item in resolved["conflictSignals"]})
            check("conflict-resolution-rules", actual, sorted(expected["conflictResolutionRules"]))
    elif expected["authorityGate"] == "PASS":
        checks.append(
            {
                "name": "resolution",
                "expected": "resolved",
                "actual": "blocked-by-authority-gate",
                "pass": False,
            }
        )

    passed = all(item["pass"] for item in checks)
    return {
        "schemaVersion": "project-integration-scenario-result/v1",
        "scenarioId": scenario["id"],
        "gate": "PASS" if passed else "NO_GO",
        "snapshotFingerprint": snapshot["snapshotFingerprint"],
        "sourceRevision": snapshot["sourceRevision"],
        "resolutionId": resolved["resolutionId"] if resolved else None,
        "checks": checks,
    }
