from __future__ import annotations

from pathlib import Path
from typing import Any

from .loader import load_capabilities
from .project import load_project_state


def _workflow_asset(repository_root: Path) -> dict[str, Any]:
    for capability in load_capabilities(Path(repository_root)):
        if capability.id == "workflow:agent-design:design-discussion" and capability.asset.get("lifecycle") == "ACTIVE":
            return capability.asset
    raise KeyError("workflow:agent-design:design-discussion")


def next_workflow_stages(repository_root: Path, stage: str) -> list[str]:
    workflow = _workflow_asset(repository_root)["workflow"]
    return list(workflow.get("allowedTransitions", {}).get(stage, []))


def _bullets(values: list[str], *, empty: str = "None") -> str:
    if not values:
        return f"- {empty}"
    return "\n".join(f"- {value}" for value in values)


def materialize_discussion_contract(
    repository_root: Path,
    project_root: Path,
    resolved_context: dict[str, Any],
    *,
    persist_path: Path | None = None,
) -> str:
    root = Path(repository_root)
    project = Path(project_root)
    state = load_project_state(root, project)
    workflow = _workflow_asset(root)["workflow"]
    stage = resolved_context["stage"]
    next_stages = workflow.get("allowedTransitions", {}).get(stage, [])
    exit_conditions = workflow.get("exitConditions", {}).get(stage, [])
    closure_conditions = workflow.get("closureConditions", {}).get(stage, [])
    background = list(dict.fromkeys([
        *resolved_context.get("projectAuthorityReferences", []),
        *state.get("baselines", []),
        *state.get("assumptions", []),
        *state.get("openDecisions", []),
    ]))
    closed_lines = [
        f"{topic['topicId']} → {topic.get('baselineReference') or 'no baseline reference'}"
        for topic in resolved_context.get("closedTopics", [])
    ]
    selected = [
        f"{item['id']}@{item['version']} ({item['contentHash'][:12]})"
        for item in resolved_context.get("selectedCapabilities", [])
    ]
    conflict_lines = [
        f"{item['sharedCapability']} conflicts with {item['projectReference']}; {item['resolutionRule']}"
        for item in resolved_context.get("conflictSignals", [])
    ]
    constraints = [
        "Project canonical authority takes precedence over generic shared guidance (PROJECT_TRUTH_WINS).",
        "CLOSED topics must not be reopened without an explicit represented reopen signal and human authority.",
        "Generated discussion context is not canonical project truth.",
        *conflict_lines,
    ]
    core_questions = [
        f"Which authoritative references govern topic `{resolved_context['topic']}`?",
        f"What must remain true while producing `{resolved_context['requestedOutput']}`?",
        "Which decisions require human authority rather than agent inference?",
    ]
    non_goals = [
        "Do not silently change project decisions, topic closure state, or shared capability lifecycle.",
        "Do not copy project-specific truth into the shared harness as reusable knowledge.",
    ]
    expected = [resolved_context["requestedOutput"], *selected]
    closure = [*exit_conditions, *closure_conditions]
    text = "\n".join(
        [
            "# Discussion Contract",
            "",
            "## Topic",
            f"- Project: {resolved_context['project']}",
            f"- Topic: {resolved_context['topic']}",
            f"- Stage: {stage}",
            f"- Intent: {resolved_context['intent']}",
            f"- Topic Guard: {resolved_context['topicGuard']}",
            "",
            "## Background References",
            _bullets(background),
            "",
            "## Known CLOSED Topics",
            _bullets(closed_lines),
            "",
            "## Scope",
            f"- Produce: {resolved_context['requestedOutput']}",
            f"- Runtime: {resolved_context['runtime']}",
            "",
            "## Non-Goals",
            _bullets(non_goals),
            "",
            "## Core Questions",
            _bullets(core_questions),
            "",
            "## Constraints",
            _bullets(constraints),
            "",
            "## Expected Outputs",
            _bullets(expected),
            "",
            "## Closure Criteria",
            _bullets(closure, empty="No automatic closure condition; human authority remains required where applicable."),
            "",
            "## Next Stage",
            _bullets(list(next_stages), empty="No workflow transition is defined."),
            "",
        ]
    )
    if persist_path is not None:
        target = Path(persist_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return text


def route_next_topics(repository_root: Path, project_root: Path, *, current_topic: str) -> dict[str, Any]:
    root = Path(repository_root)
    state = load_project_state(root, project_root)
    status = {topic["topicId"]: topic["status"] for topic in state["topics"]}
    topic_by_id = {topic["topicId"]: topic for topic in state["topics"]}
    requested = {item["topicId"]: item for item in state.get("nextTopicCandidates", [])}
    candidate_ids = list(requested)
    for topic in state["topics"]:
        if topic["topicId"] != current_topic and topic["status"] != "CLOSED" and topic["topicId"] not in candidate_ids:
            candidate_ids.append(topic["topicId"])
    candidates: list[dict[str, Any]] = []
    status_priority = {"IN_PROGRESS": 0, "OPEN": 1}
    for topic_id in candidate_ids:
        topic = topic_by_id.get(topic_id, {"topicId": topic_id, "status": "OPEN", "dependsOn": requested.get(topic_id, {}).get("dependsOn", [])})
        if topic.get("status") == "CLOSED":
            continue
        dependencies = list(requested.get(topic_id, {}).get("dependsOn", topic.get("dependsOn", [])))
        satisfied = all(status.get(dep) == "CLOSED" for dep in dependencies)
        candidate = {
            "topicId": topic_id,
            "eligible": satisfied,
            "reason": requested.get(topic_id, {}).get("reason"),
            "rankingInputs": {
                "status": topic.get("status", "OPEN"),
                "dependencies": dependencies,
                "dependenciesSatisfied": satisfied,
                "dependencyCount": len(dependencies),
                "currentStage": state["currentStage"],
                "workflowNextStages": next_workflow_stages(root, state["currentStage"]),
            },
        }
        candidates.append(candidate)
    candidates.sort(
        key=lambda item: (
            not item["eligible"],
            status_priority.get(item["rankingInputs"]["status"], 9),
            item["rankingInputs"]["dependencyCount"],
            item["topicId"],
        )
    )
    return {
        "schemaVersion": "next-topic-routing/v1",
        "project": state["project"],
        "currentTopic": current_topic,
        "usesSemanticPlanner": False,
        "candidates": candidates,
    }
