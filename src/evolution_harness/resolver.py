from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .catalog import build_design_active_catalog
from .hashing import canonical_json_bytes, sha256_bytes
from .project import load_profile, load_project_binding, load_project_state
from .registry import build_design_registry


def _load_asset(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    path = root / entry["location"] / "asset.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _bound_reasons(root: Path, binding: dict[str, Any]) -> dict[str, list[str]]:
    reasons: dict[str, list[str]] = {}
    for profile_id in binding["profiles"]:
        profile = load_profile(root, profile_id)
        for capability_id in profile["capabilities"]:
            reasons.setdefault(capability_id, []).append("explicit-profile")
            reasons[capability_id].append(f"profile:{profile_id}")
    for capability_id in binding["capabilities"]:
        reasons.setdefault(capability_id, []).append("explicit-binding")
    for capability_id in binding["extensions"]:
        reasons.setdefault(capability_id, []).append("project-extension")
    return reasons


def _scope_reasons(entry: dict[str, Any], *, intent: str, stage: str, runtime: str) -> tuple[bool, list[str], list[str]]:
    scope = entry.get("scope", {})
    selected: list[str] = []
    excluded: list[str] = []
    runtimes = scope.get("runtime", [])
    if runtimes and runtime not in runtimes:
        excluded.append("runtime-mismatch")
    else:
        selected.append("runtime-match")
    stages = scope.get("stage", [])
    if stages and stage not in stages:
        excluded.append("stage-mismatch")
    elif stages:
        selected.append("stage-match")
    intents = scope.get("intent", [])
    if intents and intent not in intents:
        excluded.append("intent-mismatch")
    elif intents:
        selected.append("intent-match")
    return not excluded, selected, excluded


def _classify_inactive(capability_id: str, current_registry: dict[str, dict[str, Any]], superseded_ids: set[str]) -> str:
    if capability_id in superseded_ids:
        return "superseded"
    entry = current_registry.get(capability_id)
    if entry is None:
        return "not-found"
    if entry["validity"] == "INVALID":
        return "invalid"
    if entry["validity"] == "QUESTIONED":
        return "questioned"
    if entry["lifecycle"] == "DEPRECATED":
        return "deprecated"
    if entry["lifecycle"] == "RETIRED":
        return "retired"
    return "not-active-catalog"


def resolve_design_context(
    repository_root: Path,
    project_root: Path,
    *,
    intent: str,
    topic: str,
    requested_output: str,
    runtime: str,
    explicit_stage: str | None = None,
    reopen_signal: str | None = None,
) -> dict[str, Any]:
    root = Path(repository_root)
    project = Path(project_root)
    state = load_project_state(root, project)
    binding = load_project_binding(root, project)
    stage = explicit_stage or state["currentStage"]
    topic_state = next((item for item in state["topics"] if item["topicId"] == topic), None)
    closed_topics = [
        {
            "topicId": item["topicId"],
            "baselineReference": item.get("baselineReference"),
            "reopenConditions": item.get("reopenConditions", []),
        }
        for item in state["topics"] if item["status"] == "CLOSED"
    ]
    topic_guard = "OPEN_OR_IN_PROGRESS"
    if topic_state and topic_state["status"] == "CLOSED":
        if reopen_signal and reopen_signal in topic_state.get("reopenConditions", []):
            topic_guard = "REOPEN_REVIEW_REQUIRED"
        else:
            topic_guard = "DO_NOT_REOPEN"

    catalog = build_design_active_catalog(root, write=False)
    active = {entry["id"]: entry for entry in catalog["entries"]}
    registry = build_design_registry(root, write=False)
    current_registry = {entry["id"]: entry for entry in registry["entries"] if entry["isCurrent"]}
    eligible_current = [entry for entry in current_registry.values() if entry["lifecycle"] == "ACTIVE" and entry["validity"] == "VALID"]
    superseded_ids = {target for entry in eligible_current for target in entry.get("relationships", {}).get("supersedes", [])}
    bound = _bound_reasons(root, binding)
    disabled = set(binding["disabledCapabilities"])
    excluded_map: dict[str, set[str]] = {}
    selected_reasons: dict[str, set[str]] = {}

    def exclude(capability_id: str, reason: str) -> None:
        excluded_map.setdefault(capability_id, set()).add(reason)

    def select(capability_id: str, *reasons: str) -> bool:
        if capability_id in disabled:
            exclude(capability_id, "disabled")
            return False
        entry = active.get(capability_id)
        if entry is None:
            exclude(capability_id, _classify_inactive(capability_id, current_registry, superseded_ids))
            return False
        selected_reasons.setdefault(capability_id, set()).update(reasons)
        return True

    workflow_entry = active.get("workflow:agent-design:design-discussion") if "workflow:agent-design:design-discussion" in bound else None
    workflow_asset = _load_asset(root, workflow_entry) if workflow_entry else None
    workflow_stage = stage if workflow_asset and stage in workflow_asset["workflow"]["stages"] else None
    human_gates = list(workflow_asset["workflow"].get("humanGates", {}).get(stage, [])) if workflow_asset else []

    if topic_guard == "DO_NOT_REOPEN":
        for capability_id in bound:
            exclude(capability_id, "closed-topic")
    else:
        for capability_id, bound_reasons in bound.items():
            if capability_id in disabled:
                exclude(capability_id, "disabled")
                continue
            entry = active.get(capability_id)
            if entry is None:
                exclude(capability_id, _classify_inactive(capability_id, current_registry, superseded_ids))
                continue
            matches, positive, negative = _scope_reasons(entry, intent=intent, stage=stage, runtime=runtime)
            if matches:
                select(capability_id, *bound_reasons, *positive)
            else:
                for reason in negative:
                    exclude(capability_id, reason)

        if workflow_asset:
            for capability_id in workflow_asset["workflow"].get("requiredSkills", {}).get(stage, []):
                select(capability_id, "workflow-required", f"workflow-stage:{stage}")

        queue = list(selected_reasons)
        inspected: set[str] = set()
        while queue:
            parent = queue.pop(0)
            if parent in inspected:
                continue
            inspected.add(parent)
            entry = active.get(parent)
            if not entry:
                continue
            for dependency in entry.get("relationships", {}).get("dependsOn", []):
                if select(dependency, f"dependency-of:{parent}") and dependency not in inspected:
                    queue.append(dependency)

    selected: list[dict[str, Any]] = []
    required_self_review: list[str] = []
    for capability_id in sorted(selected_reasons):
        entry = active[capability_id]
        item = {
            "id": capability_id,
            "kind": entry["kind"],
            "version": entry["version"],
            "contentHash": entry["contentHash"],
            "selectedBecause": sorted(selected_reasons[capability_id]),
        }
        selected.append(item)
        asset = _load_asset(root, entry)
        for review in asset.get("skill", {}).get("selfReview", []):
            if review not in required_self_review:
                required_self_review.append(review)

    conflict_signals: list[dict[str, Any]] = []
    selected_ids = set(selected_reasons)
    for constraint in state.get("projectConstraints", []):
        for capability_id in constraint["conflictsWithCapabilities"]:
            if capability_id in selected_ids:
                conflict_signals.append(
                    {
                        "sharedCapability": capability_id,
                        "projectReference": constraint["reference"],
                        "conflictType": constraint["conflictType"],
                        "resolutionRule": "PROJECT_TRUTH_WINS",
                        "reviewRecommended": True,
                    }
                )

    excluded = [
        {"id": capability_id, "excludedBecause": sorted(reasons)}
        for capability_id, reasons in sorted(excluded_map.items())
        if capability_id not in selected_reasons
    ]
    resolution_payload = {
        "project": state["project"], "topic": topic, "stage": stage, "intent": intent,
        "runtime": runtime, "selected": [(item["id"], item["version"], item["contentHash"]) for item in selected],
        "topicGuard": topic_guard, "reopenSignal": reopen_signal,
    }
    resolution_id = "resolution:" + sha256_bytes(canonical_json_bytes(resolution_payload))[:24]
    return {
        "schemaVersion": "resolved-design-context/v1",
        "resolutionId": resolution_id,
        "project": state["project"],
        "topic": topic,
        "stage": stage,
        "intent": intent,
        "runtime": runtime,
        "requestedOutput": requested_output,
        "topicGuard": topic_guard,
        "reopenSignal": reopen_signal,
        "selectedCapabilities": selected,
        "projectAuthorityReferences": state["projectAuthorityReferences"],
        "closedTopics": closed_topics,
        "protectedDecisions": state["protectedDecisions"],
        "workflowStage": workflow_stage,
        "humanGates": human_gates,
        "requiredSelfReview": required_self_review,
        "conflictSignals": conflict_signals,
        "semanticSelectionCandidates": [],
        "explain": {"selected": selected, "excluded": excluded},
    }
