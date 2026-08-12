from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import CapabilityAsset, ValidationIssue


def load_promotion_ledger(repository_root: Path) -> dict[str, Any]:
    path = Path(repository_root) / "core" / "governance" / "promotion-ledger.yaml"
    if not path.exists():
        return {"entries": []}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"entries": []}


def load_bootstrap_baseline(repository_root: Path) -> dict[str, Any]:
    path = Path(repository_root) / "core" / "governance" / "bootstrap-baseline.yaml"
    if not path.exists():
        return {"authorizedSeeds": []}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"authorizedSeeds": []}


def validate_promotion_authority(repository_root: Path, capabilities: list[CapabilityAsset]) -> list[ValidationIssue]:
    ledger = load_promotion_ledger(repository_root)
    baseline = load_bootstrap_baseline(repository_root)
    entries = {(e.get("capabilityId"), e.get("version")): e for e in ledger.get("entries", [])}
    bootstrap_keys = set(baseline.get("authorizedSeeds", []))
    issues: list[ValidationIssue] = []
    for capability in capabilities:
        key = (capability.id, capability.version)
        entry = entries.get(key)
        key_text = f"{capability.id}@{capability.version}"
        if not entry:
            issues.append(ValidationIssue("UNAUTHORIZED_CANONICAL_VERSION", f"no promotion/bootstrap ledger entry for {key_text}", str(capability.asset_path)))
            continue
        if entry.get("contentHash") != capability.content_hash:
            issues.append(
                ValidationIssue(
                    "PROMOTED_VERSION_MUTATED",
                    f"promoted/bootstrap content changed without a new semantic version: {key_text}",
                    str(capability.asset_path),
                    {"expected": entry.get("contentHash"), "actual": capability.content_hash},
                )
            )
        if entry.get("authorization") == "BOOTSTRAP_AUTHORIZED" and key_text not in bootstrap_keys:
            issues.append(ValidationIssue("BOOTSTRAP_SCOPE_VIOLATION", f"bootstrap authorization not present in cutoff baseline: {key_text}"))
    return issues
