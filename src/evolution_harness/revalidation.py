from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable, Any

from .loader import load_capabilities


def _as_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def check_revalidation(
    repository_root: Path,
    *,
    as_of: str | date,
    triggers: Iterable[str] = (),
) -> dict[str, Any]:
    root = Path(repository_root)
    today = _as_date(as_of)
    trigger_set = set(triggers)
    rows: list[dict[str, Any]] = []
    for capability in sorted(load_capabilities(root), key=lambda cap: (cap.id, cap.version)):
        asset = capability.asset
        reasons: list[str] = []
        validity = asset.get("validity", "VALID")
        if validity in {"QUESTIONED", "INVALID"}:
            reasons.append(f"validity:{validity}")
        review_after = asset.get("reviewAfter")
        if review_after and date.fromisoformat(review_after) <= today:
            reasons.append("review-due")
        for trigger in sorted(trigger_set.intersection(asset.get("revalidationTriggers", []))):
            reasons.append(f"trigger:{trigger}")
        rows.append(
            {
                "id": capability.id,
                "version": capability.version,
                "status": "REQUIRED" if reasons else "CURRENT",
                "reasons": reasons,
            }
        )
    return {
        "schemaVersion": "revalidation-check/v1",
        "asOf": today.isoformat(),
        "triggers": sorted(trigger_set),
        "capabilities": rows,
        "requiredCount": sum(1 for row in rows if row["status"] == "REQUIRED"),
    }
