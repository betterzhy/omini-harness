from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .evals import has_passing_eval, load_eval_definitions
from .identity import parse_capability_id, validate_semver
from .loader import load_capabilities
from .schema import SchemaStore

_TRIAGE_DECISIONS = {
    "IGNORE",
    "PERSONAL_PREFERENCE",
    "PROJECT_FACT",
    "PROJECT_EXPERIENCE",
    "CROSS_PROJECT_CANDIDATE",
}
_KIND_DIR = {
    "principle": "principles",
    "framework": "frameworks",
    "skill": "skills",
    "workflow": "workflows",
}


@dataclass(slots=True)
class LearningError(RuntimeError):
    code: str
    message: str
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.message)


def _safe_id(value: str) -> str:
    return value.replace(":", "__")


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _experience_paths(repository_root: Path) -> list[Path]:
    root = Path(repository_root) / "design" / "learning" / "experiences"
    return sorted(root.glob("*.yaml")) if root.exists() else []


def _find_experience(repository_root: Path, experience_id: str) -> tuple[Path, dict[str, Any]]:
    for path in _experience_paths(repository_root):
        value = _load_yaml(path)
        if value.get("experienceId") == experience_id:
            return path, value
    raise LearningError("EXPERIENCE_NOT_FOUND", f"experience not found: {experience_id}")


def capture_experience(repository_root: Path, experience: dict[str, Any]) -> Path:
    root = Path(repository_root)
    store = SchemaStore(root)
    store.validate("design/schemas/experience.schema.json", experience)
    for path in _experience_paths(root):
        if _load_yaml(path).get("experienceId") == experience["experienceId"]:
            raise LearningError("DUPLICATE_EXPERIENCE", f"experience already exists: {experience['experienceId']}")
    path = root / "design" / "learning" / "experiences" / f"{_safe_id(experience['experienceId'])}.yaml"
    _write_yaml(path, experience)
    return path


def triage_experience(repository_root: Path, experience_id: str, decision: str) -> dict[str, Any]:
    if decision not in _TRIAGE_DECISIONS:
        raise LearningError("TRIAGE_DECISION_INVALID", f"unsupported triage decision: {decision}")
    root = Path(repository_root)
    path, experience = _find_experience(root, experience_id)
    experience["triageStatus"] = "TRIAGED"
    experience["triageDecision"] = decision
    SchemaStore(root).validate("design/schemas/experience.schema.json", experience)
    _write_yaml(path, experience)
    return experience


def _candidate_paths(repository_root: Path) -> list[Path]:
    root = Path(repository_root) / "design" / "learning" / "candidates"
    return sorted(root.glob("*/candidate.yaml")) if root.exists() else []


def _find_candidate(repository_root: Path, candidate_id: str) -> tuple[Path, dict[str, Any]]:
    for path in _candidate_paths(repository_root):
        value = _load_yaml(path)
        if value.get("candidateId") == candidate_id:
            return path, value
    raise LearningError("CANDIDATE_NOT_FOUND", f"candidate not found: {candidate_id}")


def _validate_proposed_capability(root: Path, asset: dict[str, Any]) -> None:
    identity = parse_capability_id(asset.get("id", ""))
    validate_semver(asset.get("version", ""))
    if asset.get("kind") != identity.kind.upper():
        raise LearningError("IDENTITY_KIND_MISMATCH", "proposed capability kind does not match identity")
    SchemaStore(root).validate(f"design/schemas/{identity.kind}.schema.json", asset)


def create_candidate(
    repository_root: Path,
    candidate: dict[str, Any],
    proposed_asset: dict[str, Any],
    proposed_content: str,
) -> Path:
    root = Path(repository_root)
    store = SchemaStore(root)
    store.validate("design/schemas/candidate.schema.json", candidate)
    _validate_proposed_capability(root, proposed_asset)
    if not proposed_content.strip():
        raise LearningError("PROPOSED_CONTENT_REQUIRED", "candidate proposed content must not be empty")
    if candidate["operation"] != "SUPERSEDE" and candidate["targetCapability"] != proposed_asset["id"]:
        raise LearningError("CANDIDATE_TARGET_MISMATCH", "candidate target must match proposed capability identity")
    for source_id in candidate["sourceExperiences"]:
        _find_experience(root, source_id)
    for existing in _candidate_paths(root):
        if _load_yaml(existing).get("candidateId") == candidate["candidateId"]:
            raise LearningError("DUPLICATE_CANDIDATE", f"candidate already exists: {candidate['candidateId']}")
    candidate_dir = root / "design" / "learning" / "candidates" / _safe_id(candidate["candidateId"])
    _write_yaml(candidate_dir / "candidate.yaml", candidate)
    _write_yaml(candidate_dir / "proposed" / "asset.yaml", proposed_asset)
    content_path = candidate_dir / "proposed" / "content.md"
    content_path.parent.mkdir(parents=True, exist_ok=True)
    content_path.write_text(proposed_content, encoding="utf-8")
    return candidate_dir


def _semver_tuple(version: str) -> tuple[int, int, int]:
    validate_semver(version)
    return tuple(int(part) for part in version.split("."))  # type: ignore[return-value]


def is_monotonic_scope_broadening(old_scope: dict[str, Any], new_scope: dict[str, Any]) -> bool:
    keys = set(old_scope) | set(new_scope)
    strict = False
    for key in keys:
        old_value = old_scope.get(key)
        new_value = new_scope.get(key)
        if old_value is None:
            if new_value not in (None, [], {}):
                return False
            continue
        if new_value is None:
            strict = True
            continue
        if isinstance(old_value, list) and isinstance(new_value, list):
            old_set = set(old_value)
            new_set = set(new_value)
            if not old_set.issubset(new_set):
                return False
            if new_set != old_set:
                strict = True
            continue
        if old_value != new_value:
            return False
    return strict


def _current_target(root: Path, capability_id: str):
    matches = [cap for cap in load_capabilities(root) if cap.id == capability_id]
    if not matches:
        return None
    return max(matches, key=lambda cap: _semver_tuple(cap.version))


def _ensure_sources_triaged(root: Path, candidate: dict[str, Any]) -> None:
    for experience_id in candidate["sourceExperiences"]:
        _, experience = _find_experience(root, experience_id)
        if experience.get("triageStatus") != "TRIAGED":
            raise LearningError("SOURCE_EXPERIENCE_UNTRIAGED", f"source experience must be triaged: {experience_id}")


def _ensure_transfer_evidence(root: Path, candidate: dict[str, Any], proposed_asset: dict[str, Any]) -> None:
    transfer = candidate.get("transferEvidence")
    if not transfer:
        raise LearningError("TRANSFER_EVIDENCE_REQUIRED", "BROADEN_SCOPE requires transfer evidence")
    try:
        SchemaStore(root).validate("design/schemas/candidate.schema.json", candidate)
    except Exception as exc:
        raise LearningError("TRANSFER_EVIDENCE_REQUIRED", "BROADEN_SCOPE transfer evidence is incomplete") from exc
    target = _current_target(root, candidate["targetCapability"])
    if target is None:
        raise LearningError("TARGET_NOT_FOUND", f"target capability not found: {candidate['targetCapability']}")
    if not is_monotonic_scope_broadening(target.asset.get("scope", {}), proposed_asset.get("scope", {})):
        raise LearningError("SCOPE_NOT_BROADENED", "BROADEN_SCOPE proposed scope is not a monotonic broadening")
    transfer_eval = transfer["transferEval"]
    if not has_passing_eval(root, transfer_eval, proposed_asset["id"], proposed_asset["version"]):
        raise LearningError("TRANSFER_EVAL_REQUIRED", f"passing transfer eval required: {transfer_eval}")


def _ensure_evals(root: Path, candidate: dict[str, Any], proposed_asset: dict[str, Any]) -> None:
    definitions = load_eval_definitions(root)
    for eval_id in candidate.get("evalRequirements", []):
        if eval_id not in definitions:
            raise LearningError("EVAL_REQUIRED", f"required eval definition not found: {eval_id}")
        if definitions[eval_id]["targetCapability"] != proposed_asset["id"]:
            raise LearningError("EVAL_REQUIRED", f"required eval targets another capability: {eval_id}")
        if not has_passing_eval(root, eval_id, proposed_asset["id"], proposed_asset["version"]):
            raise LearningError("EVAL_REQUIRED", f"passing eval result required: {eval_id}")


def _validate_operation(root: Path, candidate: dict[str, Any], proposed_asset: dict[str, Any]) -> None:
    operation = candidate["operation"]
    existing_same_id = [cap for cap in load_capabilities(root) if cap.id == proposed_asset["id"]]
    target = _current_target(root, candidate["targetCapability"])
    if operation == "CREATE":
        if existing_same_id:
            raise LearningError("TARGET_ALREADY_EXISTS", f"CREATE target already exists: {proposed_asset['id']}")
        return
    if target is None:
        raise LearningError("TARGET_NOT_FOUND", f"target capability not found: {candidate['targetCapability']}")
    if operation in {"UPDATE", "BROADEN_SCOPE", "NARROW_SCOPE"} and proposed_asset["id"] != candidate["targetCapability"]:
        raise LearningError("CANDIDATE_TARGET_MISMATCH", "update/scope operation must preserve capability identity")
    if operation == "SUPERSEDE" and candidate["targetCapability"] not in proposed_asset.get("relationships", {}).get("supersedes", []):
        raise LearningError("SUPERSESSION_TARGET_REQUIRED", "SUPERSEDE proposed capability must explicitly supersede the target capability")
    if existing_same_id:
        highest = max(_semver_tuple(cap.version) for cap in existing_same_id)
        proposed_version = _semver_tuple(proposed_asset["version"])
        if proposed_version <= highest:
            raise LearningError("VERSION_NOT_NEW", "proposed semantic version must be newer than every existing version")
    if operation == "NARROW_SCOPE":
        if is_monotonic_scope_broadening(target.asset.get("scope", {}), proposed_asset.get("scope", {})):
            raise LearningError("SCOPE_NOT_NARROWED", "NARROW_SCOPE cannot broaden applicability")


def _destination_for(root: Path, asset: dict[str, Any]) -> Path:
    identity = parse_capability_id(asset["id"])
    base = root / "design" / "capabilities" / _KIND_DIR[identity.kind] / identity.name
    if not (base / "asset.yaml").exists():
        return base
    return base / "versions" / asset["version"]


def _append_ledger(root: Path, capability, candidate: dict[str, Any]) -> None:
    path = root / "core" / "governance" / "promotion-ledger.yaml"
    ledger = _load_yaml(path) if path.exists() else {"schemaVersion": "promotion-ledger/v1", "entries": []}
    entries = ledger.setdefault("entries", [])
    if any(e.get("capabilityId") == capability.id and e.get("version") == capability.version for e in entries):
        raise LearningError("VERSION_ALREADY_PROMOTED", f"promotion ledger already contains {capability.id}@{capability.version}")
    entries.append(
        {
            "capabilityId": capability.id,
            "version": capability.version,
            "contentHash": capability.content_hash,
            "authorization": "PROMOTED",
            "authorizedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "authorityDecision": candidate["authorityDecision"],
            "sourceReference": f"candidate://{candidate['candidateId']}",
        }
    )
    entries.sort(key=lambda e: (e.get("capabilityId", ""), _semver_tuple(e.get("version", "0.0.0"))))
    _write_yaml(path, ledger)


def promote_candidate(repository_root: Path, candidate_id: str, *, apply: bool = False) -> dict[str, Any]:
    root = Path(repository_root)
    candidate_path, candidate = _find_candidate(root, candidate_id)
    candidate_dir = candidate_path.parent
    proposed_path = candidate_dir / "proposed" / "asset.yaml"
    content_path = candidate_dir / "proposed" / "content.md"
    if not proposed_path.exists() or not content_path.exists():
        raise LearningError("PROPOSED_ASSET_MISSING", "candidate proposed capability is incomplete")
    proposed_asset = _load_yaml(proposed_path)
    _validate_proposed_capability(root, proposed_asset)

    if candidate.get("promotionStatus") != "AUTHORIZED" or candidate.get("authorityDecision") != "APPROVE":
        raise LearningError("AUTHORITY_REQUIRED", "explicit human/decision authority approval is required")
    _ensure_sources_triaged(root, candidate)
    _validate_operation(root, candidate, proposed_asset)
    if candidate["operation"] == "BROADEN_SCOPE":
        _ensure_transfer_evidence(root, candidate, proposed_asset)
    _ensure_evals(root, candidate, proposed_asset)

    readiness = {
        "candidateId": candidate_id,
        "capabilityId": proposed_asset["id"],
        "version": proposed_asset["version"],
        "mechanicalReadiness": "PASS",
        "authorityStatus": "APPROVED",
        "applied": False,
    }
    if not apply:
        return readiness

    destination = _destination_for(root, proposed_asset)
    if destination.exists():
        raise LearningError("TARGET_LOCATION_EXISTS", f"promotion destination already exists: {destination}")
    destination.mkdir(parents=True, exist_ok=False)
    _write_yaml(destination / "asset.yaml", proposed_asset)
    (destination / proposed_asset.get("contentFile", "content.md")).write_text(content_path.read_text(encoding="utf-8"), encoding="utf-8")
    promoted = next(
        cap for cap in load_capabilities(root)
        if cap.id == proposed_asset["id"] and cap.version == proposed_asset["version"] and cap.asset_path.parent == destination
    )
    _append_ledger(root, promoted, candidate)
    candidate["promotionStatus"] = "INTEGRATED"
    _write_yaml(candidate_path, candidate)
    readiness["applied"] = True
    readiness["contentHash"] = promoted.content_hash
    readiness["location"] = destination.relative_to(root).as_posix()
    return readiness
