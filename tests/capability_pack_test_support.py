from __future__ import annotations

from pathlib import Path

import yaml

from evolution_harness.capability_pack_registry import _canonical_registry_entry
from evolution_harness.generated import write_generated_json
from evolution_harness.hashing import canonical_json_bytes, sha256_bytes


WEB_REGISTRATION_ID = "pack:web-high-fidelity"
JAVA_CAPABILITY_ID = "framework:java:java-engineering-standard"


def _remove_java_from_copied_pay_integration(root: Path) -> None:
    """Keep full-repository copies consistent with the Web-only registration fixture."""
    integration = root / "integrations/pay-nexus-shadow"
    if not integration.exists():
        return

    binding_path = integration / "control-plane/.agent-evolution/capabilities.yaml"
    binding = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
    binding["capabilities"] = [
        capability
        for capability in binding["capabilities"]
        if capability != JAVA_CAPABILITY_ID
    ]
    binding_path.write_text(yaml.safe_dump(binding, sort_keys=False), encoding="utf-8")

    for scenario_path in sorted((integration / "scenarios").glob("*.yaml")):
        scenario = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
        selected = scenario.get("expected", {}).get("selectedCapabilities")
        if selected is None or JAVA_CAPABILITY_ID not in selected:
            continue
        scenario["expected"]["selectedCapabilities"] = [
            capability for capability in selected if capability != JAVA_CAPABILITY_ID
        ]
        scenario_path.write_text(
            yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8"
        )

    from evolution_harness.project import build_capability_lock

    build_capability_lock(root, integration / "control-plane", write=True)


def retain_web_registration_fixture(root: Path) -> None:
    """Keep legacy copied-repository tests bounded to their Web Pack fixture."""
    registrations_path = root / "core/registries/capability-packs.yaml"
    registrations = yaml.safe_load(registrations_path.read_text(encoding="utf-8"))
    registrations = [
        item
        for item in registrations
        if item["registrationId"] == WEB_REGISTRATION_ID
    ]
    if len(registrations) != 1:
        raise AssertionError("Web capability pack test registration is missing or ambiguous")
    registrations_path.write_text(
        yaml.safe_dump(registrations, sort_keys=False), encoding="utf-8"
    )

    generated_path = root / "generated/registries/capability-pack-registry.json"
    if generated_path.exists():
        canonical_entries = [
            _canonical_registry_entry(registration)
            for registration in registrations
        ]
        write_generated_json(
            generated_path,
            {
                "schemaVersion": "capability-pack-registry/v1",
                "sourceRevision": "content-sha256:"
                + sha256_bytes(canonical_json_bytes(canonical_entries)),
                "entries": registrations,
            },
        )
    _remove_java_from_copied_pay_integration(root)
