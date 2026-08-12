from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .identity import IdentityError, parse_capability_id
from .models import CapabilityAsset, ValidationIssue

_RELATION_ALLOWED: dict[str, dict[str, set[str]]] = {
    "dependsOn": {
        "PRINCIPLE": {"PRINCIPLE", "FRAMEWORK"},
        "FRAMEWORK": {"PRINCIPLE", "FRAMEWORK"},
        "SKILL": {"PRINCIPLE", "FRAMEWORK", "SKILL"},
        "WORKFLOW": {"PRINCIPLE", "FRAMEWORK", "SKILL", "WORKFLOW"},
    },
    "extends": {
        "PRINCIPLE": {"PRINCIPLE"},
        "FRAMEWORK": {"FRAMEWORK"},
        "SKILL": {"SKILL"},
        "WORKFLOW": {"WORKFLOW"},
    },
    "derivedFrom": {
        "PRINCIPLE": {"PRINCIPLE", "FRAMEWORK", "SKILL", "WORKFLOW"},
        "FRAMEWORK": {"PRINCIPLE", "FRAMEWORK", "SKILL", "WORKFLOW"},
        "SKILL": {"PRINCIPLE", "FRAMEWORK", "SKILL", "WORKFLOW"},
        "WORKFLOW": {"PRINCIPLE", "FRAMEWORK", "SKILL", "WORKFLOW"},
    },
    "supersedes": {
        "PRINCIPLE": {"PRINCIPLE"},
        "FRAMEWORK": {"FRAMEWORK"},
        "SKILL": {"SKILL"},
        "WORKFLOW": {"WORKFLOW"},
    },
    "constrainedBy": {
        "PRINCIPLE": {"PRINCIPLE", "FRAMEWORK"},
        "FRAMEWORK": {"PRINCIPLE", "FRAMEWORK"},
        "SKILL": {"PRINCIPLE", "FRAMEWORK"},
        "WORKFLOW": {"PRINCIPLE", "FRAMEWORK"},
    },
}


def _kind_from_id(capability_id: str) -> str | None:
    try:
        return parse_capability_id(capability_id).kind.upper()
    except IdentityError:
        return None


def validate_skill_composition(asset: dict[str, Any], max_skill_dependencies: int = 6) -> list[ValidationIssue]:
    if asset.get("kind") != "SKILL":
        return []
    skill = asset.get("skill") or {}
    refs = set(skill.get("referencedCapabilities") or [])
    refs.update((asset.get("relationships") or {}).get("dependsOn") or [])
    skill_refs = {ref for ref in refs if _kind_from_id(ref) == "SKILL"}
    issues: list[ValidationIssue] = []
    role = skill.get("skillRole")
    if role == "LEAF" and skill_refs:
        issues.append(
            ValidationIssue(
                "LEAF_SKILL_COMPOSITION",
                f"leaf skill {asset.get('id')} may not compose skills",
                details={"skillReferences": sorted(skill_refs)},
            )
        )
    if role == "ORCHESTRATION" and len(skill_refs) > max_skill_dependencies:
        issues.append(
            ValidationIssue(
                "SKILL_COMPOSITION_BOUND",
                f"orchestration skill {asset.get('id')} composes {len(skill_refs)} skills; max is {max_skill_dependencies}",
                details={"skillReferences": sorted(skill_refs), "max": max_skill_dependencies},
            )
        )
    return issues


def validate_relationships(capabilities: Iterable[CapabilityAsset]) -> list[ValidationIssue]:
    capabilities = list(capabilities)
    known_kinds: dict[str, set[str]] = defaultdict(set)
    representative: dict[str, CapabilityAsset] = {}
    for capability in capabilities:
        known_kinds[capability.id].add(capability.kind)
        representative.setdefault(capability.id, capability)

    issues: list[ValidationIssue] = []
    graph: dict[str, set[str]] = defaultdict(set)

    for capability in capabilities:
        asset = capability.asset
        relationships = asset.get("relationships") or {}
        for relation, targets in relationships.items():
            for target in targets or []:
                if target == capability.id:
                    issues.append(ValidationIssue("SELF_REFERENCE", f"{capability.id} {relation} itself", str(capability.asset_path)))
                    continue
                if target not in known_kinds:
                    issues.append(ValidationIssue("BROKEN_REFERENCE", f"{capability.id} {relation} missing target {target}", str(capability.asset_path)))
                    continue
                target_kind = sorted(known_kinds[target])[0]
                allowed = _RELATION_ALLOWED.get(relation, {}).get(capability.kind, set())
                if target_kind not in allowed:
                    issues.append(
                        ValidationIssue(
                            "RELATION_KIND_INVALID",
                            f"{capability.kind} {relation} {target_kind} is not allowed",
                            str(capability.asset_path),
                            {"source": capability.id, "target": target, "relation": relation},
                        )
                    )
                if relation in {"dependsOn", "extends"}:
                    graph[capability.id].add(target)
        issues.extend(validate_skill_composition(asset))

        if capability.kind == "SKILL":
            for target in (asset.get("skill") or {}).get("referencedCapabilities") or []:
                if target not in known_kinds:
                    issues.append(ValidationIssue("BROKEN_REFERENCE", f"{capability.id} references missing capability {target}", str(capability.asset_path)))

    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_nodes: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        if node in visiting:
            if node in stack:
                idx = stack.index(node)
                cycle_nodes.update(stack[idx:] + [node])
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for nxt in sorted(graph.get(node, ())):
            if nxt in representative:
                visit(nxt, stack)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node, [])
    if cycle_nodes:
        issues.append(ValidationIssue("RELATION_CYCLE", "relationship dependency cycle detected", details={"nodes": sorted(cycle_nodes)}))
    return issues
