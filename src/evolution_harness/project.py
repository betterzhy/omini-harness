from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from .capability_pack_registry import (
    CapabilityVerificationSession,
    PackVerificationKey,
    VerifiedCapabilityPack,
    _get_verified_capability_pack,
    _locator_bound_blob_access_fingerprint,
    _registration_fingerprint,
)
from .catalog import build_design_active_catalog
from .hashing import canonical_json_bytes, sha256_bytes
from .registry import build_design_registry
from .schema import SchemaStore


def _freeze(value: Any) -> Any:
    if isinstance(value, VerifiedCapabilityPack):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return deepcopy(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return deepcopy(value)


@dataclass(frozen=True, slots=True)
class LockVerificationKey:
    project_root: Path
    digest: str


@dataclass(frozen=True, slots=True)
class VerifiedLockContext:
    key: LockVerificationKey
    lock: Mapping[str, Any]
    entries: Mapping[str, Mapping[str, Any]]
    verified_packs: Mapping[str, VerifiedCapabilityPack]
    _session_token: object

    def public_result(self) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        return _thaw(self.lock), {
            capability_id: _thaw(entry)
            for capability_id, entry in self.entries.items()
        }


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_project_state(repository_root: Path, project_root: Path) -> dict[str, Any]:
    root = Path(repository_root)
    path = Path(project_root) / ".agent-evolution" / "design-state.yaml"
    value = _load_yaml(path)
    SchemaStore(root).validate("core/schemas/project-design-state.schema.json", value)
    topic_ids = [item["topicId"] for item in value["topics"]]
    if len(topic_ids) != len(set(topic_ids)):
        raise ValueError("project design state contains duplicate topic ids")
    return value


def load_project_binding(repository_root: Path, project_root: Path) -> dict[str, Any]:
    root = Path(repository_root)
    path = Path(project_root) / ".agent-evolution" / "capabilities.yaml"
    value = _load_yaml(path)
    SchemaStore(root).validate("core/schemas/project-capability-binding.schema.json", value)
    return value


def load_profile(repository_root: Path, profile_id: str) -> dict[str, Any]:
    root = Path(repository_root)
    for path in sorted((root / "runtime" / "profiles").glob("*.yaml")):
        value = _load_yaml(path)
        if value.get("id") == profile_id:
            if value.get("schemaVersion") != "capability-profile/v1" or not isinstance(value.get("capabilities"), list):
                raise ValueError(f"invalid profile: {profile_id}")
            return value
    raise KeyError(f"profile not found: {profile_id}")


def bound_capability_reasons(repository_root: Path, project_root: Path) -> dict[str, list[str]]:
    root = Path(repository_root)
    binding = load_project_binding(root, project_root)
    disabled = set(binding["disabledCapabilities"])
    reasons: dict[str, list[str]] = {}
    for profile_id in binding["profiles"]:
        for capability_id in load_profile(root, profile_id)["capabilities"]:
            reasons.setdefault(capability_id, []).append(f"profile:{profile_id}")
    for capability_id in binding["capabilities"]:
        reasons.setdefault(capability_id, []).append("explicit-binding")
    for capability_id in binding["extensions"]:
        reasons.setdefault(capability_id, []).append("project-extension")
    return {capability_id: reason for capability_id, reason in reasons.items() if capability_id not in disabled}


def _declared_external_capability_ids(
    repository_root: Path, project_root: Path
) -> frozenset[str]:
    root = Path(repository_root)
    reasons = bound_capability_reasons(root, project_root)
    catalog = build_design_active_catalog(root, write=False)
    internal_ids = {entry["id"] for entry in catalog["entries"]}
    return frozenset(reasons) - internal_ids


def _build_capability_lock(
    repository_root: Path,
    project_root: Path,
    *,
    write: bool,
    verification_session: CapabilityVerificationSession,
) -> dict[str, Any]:
    root = Path(repository_root)
    project = Path(project_root)
    binding = load_project_binding(root, project)
    reasons = bound_capability_reasons(root, project)
    catalog = build_design_active_catalog(root, write=False)
    by_id = {entry["id"]: entry for entry in catalog["entries"]}
    capability_sources: list[dict[str, Any]] = []
    for capability_id in sorted(reasons):
        entry = by_id.get(capability_id)
        if entry is not None:
            capability_sources.append(
                {
                    "capabilityId": capability_id,
                    "resolvedVersion": entry["version"],
                    "contentHash": entry["contentHash"],
                }
            )
            continue
        try:
            verified_pack = _get_verified_capability_pack(
                root,
                capability_id,
                verification_session=verification_session,
            )
        except KeyError as exc:
            raise ValueError(
                f"active capability pack registration not found or ambiguous: {capability_id}"
            ) from exc
        capability_sources.append(_external_lock_source(verified_pack.registration))
    external_selected = any(
        source.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK"
        for source in capability_sources
    )
    if external_selected:
        capability_sources = [
            source
            if "sourceKind" in source
            else {**source, "sourceKind": "HARNESS_CANONICAL"}
            for source in capability_sources
        ]
        source_revision = capability_lock_v2_source_revision(capability_sources)
    else:
        source_revision = capability_lock_source_revision(capability_sources)
    capabilities = [
        {
            **source,
            "sourceHarnessRevision": source_revision,
            "resolvedBecause": reasons[source["capabilityId"]],
        }
        for source in capability_sources
    ]
    result: dict[str, Any] = {
        "schemaVersion": "capability-lock/v2" if external_selected else "capability-lock/v1",
        "project": load_project_state(root, project)["project"],
        "sourceHarnessRevision": source_revision,
        "disabledCapabilities": sorted(binding["disabledCapabilities"]),
        "capabilities": capabilities,
    }
    result["lockFingerprint"] = capability_lock_fingerprint(result)
    SchemaStore(root).validate("core/schemas/capability-lock.schema.json", result)
    if write:
        path = project / ".agent-evolution" / "capabilities.lock.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return result


def build_capability_lock(
    repository_root: Path,
    project_root: Path,
    *,
    write: bool = False,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:
    root = Path(repository_root)
    project = Path(project_root)
    declared_external_ids = _declared_external_capability_ids(root, project)
    if verification_session is None:
        with CapabilityVerificationSession(
            root,
            allowed_capability_ids=declared_external_ids,
        ) as private_session:
            with private_session._operation_lease(root, declared_external_ids):
                return _build_capability_lock(
                    root,
                    project,
                    write=write,
                    verification_session=private_session,
                )
    with verification_session._operation_lease(root, declared_external_ids):
        return _build_capability_lock(
            root,
            project,
            write=write,
            verification_session=verification_session,
        )


def capability_lock_fingerprint(lock: dict[str, Any]) -> str:
    payload = {key: value for key, value in lock.items() if key != "lockFingerprint"}
    return "sha256:" + sha256_bytes(canonical_json_bytes(payload))


def capability_lock_source_revision(capabilities: list[dict[str, Any]]) -> str:
    sources = sorted(
        [
            {
                "capabilityId": item["capabilityId"],
                "resolvedVersion": item["resolvedVersion"],
                "contentHash": item["contentHash"],
            }
            for item in capabilities
        ],
        key=lambda item: item["capabilityId"],
    )
    return "content-sha256:" + sha256_bytes(canonical_json_bytes(sources))


def _external_lock_source(registration: Mapping[str, Any]) -> dict[str, Any]:
    resolved_digest = registration["resolvedContentDigest"]
    return {
        "capabilityId": registration["capabilityId"],
        "resolvedVersion": registration["packVersion"],
        "contentHash": resolved_digest.removeprefix("sha256:"),
        "sourceKind": "EXTERNAL_CAPABILITY_PACK",
        "sourceRegistrationId": registration["registrationId"],
        "sourceCommit": registration["source"]["commit"],
        "sourceTree": registration["source"]["tree"],
        "resolvedContentDigest": resolved_digest,
        "validatorIdentity": {
            "relativePath": registration["validator"]["relativePath"],
            "sha256": registration["validator"]["sha256"],
            **(
                {
                    "environmentContract": registration["validator"][
                        "environmentContract"
                    ]
                }
                if "environmentContract" in registration["validator"]
                else {}
            ),
            **(
                {"toolchain": _thaw(registration["validator"]["toolchain"])}
                if "toolchain" in registration["validator"]
                else {}
            ),
            **(
                {
                    "gitHistoryContract": registration["validator"][
                        "gitHistoryContract"
                    ]
                }
                if "gitHistoryContract" in registration["validator"]
                else {}
            ),
            **(
                {"timeoutSeconds": registration["validator"]["timeoutSeconds"]}
                if "timeoutSeconds" in registration["validator"]
                else {}
            ),
        },
        "registrationFingerprint": _registration_fingerprint(registration),
    }


def _source_identity_keys(item: dict[str, Any]) -> tuple[str, ...]:
    common = ("capabilityId", "resolvedVersion", "contentHash", "sourceKind")
    if item["sourceKind"] == "HARNESS_CANONICAL":
        return common
    return common + (
        "sourceRegistrationId",
        "sourceCommit",
        "sourceTree",
        "resolvedContentDigest",
        "validatorIdentity",
        "registrationFingerprint",
    )


def capability_lock_v2_source_revision(capabilities: list[dict[str, Any]]) -> str:
    sources = sorted(
        [
            {key: item[key] for key in _source_identity_keys(item)}
            for item in capabilities
        ],
        key=lambda item: item["capabilityId"],
    )
    return "content-sha256:" + sha256_bytes(canonical_json_bytes(sources))


def _read_yaml_witness(path: Path) -> tuple[dict[str, Any], str]:
    data = path.read_bytes()
    value = yaml.safe_load(data.decode("utf-8")) or {}
    return value, "sha256:" + sha256_bytes(data)


def _load_project_state_witness(
    repository_root: Path, project_root: Path
) -> tuple[dict[str, Any], str]:
    root = Path(repository_root)
    path = Path(project_root) / ".agent-evolution" / "design-state.yaml"
    value, digest = _read_yaml_witness(path)
    SchemaStore(root).validate("core/schemas/project-design-state.schema.json", value)
    topic_ids = [item["topicId"] for item in value["topics"]]
    if len(topic_ids) != len(set(topic_ids)):
        raise ValueError("project design state contains duplicate topic ids")
    return value, digest


def _load_project_binding_witness(
    repository_root: Path, project_root: Path
) -> tuple[dict[str, Any], str]:
    root = Path(repository_root)
    path = Path(project_root) / ".agent-evolution" / "capabilities.yaml"
    value, digest = _read_yaml_witness(path)
    SchemaStore(root).validate(
        "core/schemas/project-capability-binding.schema.json", value
    )
    return value, digest


def _profile_and_reason_witnesses(
    repository_root: Path, binding: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    root = Path(repository_root)
    profiles: list[dict[str, Any]] = []
    reasons: dict[str, list[str]] = {}
    for profile_id in binding["profiles"]:
        matched: tuple[Path, dict[str, Any], str] | None = None
        for path in sorted((root / "runtime" / "profiles").glob("*.yaml")):
            value, digest = _read_yaml_witness(path)
            if value.get("id") == profile_id:
                if value.get("schemaVersion") != "capability-profile/v1" or not isinstance(
                    value.get("capabilities"), list
                ):
                    raise ValueError(f"invalid profile: {profile_id}")
                matched = path, value, digest
                break
        if matched is None:
            raise KeyError(f"profile not found: {profile_id}")
        path, profile, digest = matched
        profiles.append(
            {
                "profileId": profile_id,
                "path": path.relative_to(root).as_posix(),
                "sha256": digest,
                "value": profile,
            }
        )
        for capability_id in profile["capabilities"]:
            reasons.setdefault(capability_id, []).append(f"profile:{profile_id}")
    for capability_id in binding["capabilities"]:
        reasons.setdefault(capability_id, []).append("explicit-binding")
    for capability_id in binding["extensions"]:
        reasons.setdefault(capability_id, []).append("project-extension")
    disabled = set(binding["disabledCapabilities"])
    return profiles, {
        capability_id: reason
        for capability_id, reason in reasons.items()
        if capability_id not in disabled
    }


def _design_registry_input_witness(repository_root: Path) -> list[dict[str, Any]]:
    root = Path(repository_root)
    witnesses: list[dict[str, Any]] = []
    for asset_path in sorted((root / "design" / "capabilities").rglob("asset.yaml")):
        asset_data = asset_path.read_bytes()
        asset = yaml.safe_load(asset_data.decode("utf-8")) or {}
        content_path = asset_path.parent / asset.get("contentFile", "content.md")
        content_exists = content_path.exists()
        content_data = content_path.read_bytes() if content_exists else b""
        witnesses.append(
            {
                "assetPath": asset_path.relative_to(root).as_posix(),
                "assetSha256": "sha256:" + sha256_bytes(asset_data),
                "contentPath": content_path.relative_to(root).as_posix(),
                "contentExists": content_exists,
                "contentSha256": "sha256:" + sha256_bytes(content_data),
            }
        )
    return witnesses


def _load_capability_lock_witness(
    repository_root: Path, project_root: Path
) -> tuple[dict[str, Any], str]:
    root = Path(repository_root)
    project = Path(project_root)
    path = project / ".agent-evolution" / "capabilities.lock.yaml"
    if not path.exists():
        raise ValueError(f"capability lock missing: {path}")
    lock, digest = _read_yaml_witness(path)
    SchemaStore(root).validate("core/schemas/capability-lock.schema.json", lock)
    if lock["lockFingerprint"] != capability_lock_fingerprint(lock):
        raise ValueError("capability lock fingerprint mismatch")
    return lock, digest


def load_capability_lock(repository_root: Path, project_root: Path) -> dict[str, Any]:
    return _load_capability_lock_witness(repository_root, project_root)[0]


def _pack_key_witness(key: PackVerificationKey) -> dict[str, str]:
    return {
        "capabilityId": key.capability_id,
        "registrationId": key.registration_id,
        "digest": key.digest,
    }


def _record_lock_stat_locked(
    session: CapabilityVerificationSession,
    name: str,
    key: LockVerificationKey,
) -> None:
    session._counts[name] += 1
    values = session._by_lock.setdefault(key.digest, {})
    values[name] = values.get(name, 0) + 1


def _publish_verified_lock_context(
    session: CapabilityVerificationSession,
    context: VerifiedLockContext,
) -> VerifiedLockContext:
    with session._mutex:
        if session._state != "OPEN":
            raise ValueError(
                f"capability verification session is {session._state.lower()}"
            )
        contexts: dict[LockVerificationKey, VerifiedLockContext] = getattr(
            session, "_verified_lock_contexts", None
        )
        if contexts is None:
            contexts = {}
            session._verified_lock_contexts = contexts
        identities: dict[Path, LockVerificationKey] = getattr(
            session, "_lock_identity_by_project", None
        )
        if identities is None:
            identities = {}
            session._lock_identity_by_project = identities

        _record_lock_stat_locked(session, "lock_witness_recheck_count", context.key)
        prior = identities.get(context.key.project_root)
        if prior is not None and prior != context.key:
            error = ValueError(
                "capability lock identity changed within verification session"
            )
            session._poison(error)
            raise error
        identities.setdefault(context.key.project_root, context.key)
        cached = contexts.get(context.key)
        if cached is not None:
            if cached._session_token is not session._token or any(
                cached.verified_packs.get(capability_id) is not verified_pack
                for capability_id, verified_pack in context.verified_packs.items()
            ):
                error = ValueError("foreign or invalidated verified lock context")
                session._poison(error)
                raise error
            _record_lock_stat_locked(session, "lock_reuse_hit_count", context.key)
            return cached
        contexts[context.key] = context
        _record_lock_stat_locked(session, "verified_lock_count", context.key)
        return context


def _verify_capability_lock_context(
    repository_root: Path,
    project_root: Path,
    *,
    verification_session: CapabilityVerificationSession,
) -> VerifiedLockContext:
    root = Path(repository_root)
    project = Path(project_root)
    lock, lock_bytes_digest = _load_capability_lock_witness(root, project)
    if lock["schemaVersion"] == "capability-lock/v2" and not any(
        item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK"
        for item in lock["capabilities"]
    ):
        raise ValueError(
            "capability-lock/v2 requires at least one external capability pack"
        )
    state, state_bytes_digest = _load_project_state_witness(root, project)
    binding, binding_bytes_digest = _load_project_binding_witness(root, project)
    profiles, reasons = _profile_and_reason_witnesses(root, binding)
    if lock["project"] != state["project"]:
        raise ValueError("capability lock project does not match project state")
    if lock["disabledCapabilities"] != sorted(binding["disabledCapabilities"]):
        raise ValueError("capability lock binding disabledCapabilities drift")
    locked_items = {item["capabilityId"]: item for item in lock["capabilities"]}
    if len(locked_items) != len(lock["capabilities"]):
        raise ValueError("capability lock contains duplicate capability ids")
    if set(locked_items) != set(reasons):
        raise ValueError("capability lock binding capability set drift")
    if lock["schemaVersion"] == "capability-lock/v1":
        expected_source_revision = capability_lock_source_revision(lock["capabilities"])
    else:
        expected_source_revision = capability_lock_v2_source_revision(lock["capabilities"])
    if lock["sourceHarnessRevision"] != expected_source_revision:
        raise ValueError("capability lock source revision is not reproducible from exact sources")

    registry_inputs = _design_registry_input_witness(root)
    registry = build_design_registry(root, write=False)
    by_version = {(entry["id"], entry["version"]): entry for entry in registry["entries"]}
    catalog = build_design_active_catalog(root, write=False)
    if registry_inputs != _design_registry_input_witness(root):
        raise ValueError("design Registry input changed during capability lock verification")
    active_internal_ids = {entry["id"] for entry in catalog["entries"]}
    external_items = [
        item
        for item in lock["capabilities"]
        if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK"
    ]
    external_ids = {item["capabilityId"] for item in external_items}
    collisions = sorted(active_internal_ids & external_ids)
    if collisions:
        raise ValueError(
            f"external capability pack lock registration drift: {collisions[0]}"
        )
    external_by_id: dict[str, VerifiedCapabilityPack] = {}
    for item in external_items:
        capability_id = item["capabilityId"]
        try:
            external_by_id[capability_id] = _get_verified_capability_pack(
                root,
                capability_id,
                verification_session=verification_session,
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"external capability pack lock registration drift: {capability_id}"
            ) from exc
    verified: dict[str, Mapping[str, Any]] = {}
    internal_entries: dict[str, Mapping[str, Any]] = {}
    for capability_id, item in locked_items.items():
        if item["sourceHarnessRevision"] != lock["sourceHarnessRevision"]:
            raise ValueError(f"capability lock source revision mismatch: {capability_id}")
        if sorted(item["resolvedBecause"]) != sorted(reasons[capability_id]):
            raise ValueError(f"capability lock binding reasons drift: {capability_id}")
        if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK":
            verified_pack = external_by_id.get(capability_id)
            if verified_pack is None:
                raise ValueError(
                    f"external capability pack lock registration drift: {capability_id}"
                )
            expected_source = _external_lock_source(verified_pack.registration)
            actual_source = {
                key: item[key] for key in _source_identity_keys(item)
            }
            if actual_source != expected_source:
                raise ValueError(
                    f"external capability pack lock registration drift: {capability_id}"
                )
            registration_copy = _thaw(verified_pack.registration)
            locator_fingerprint = _locator_bound_blob_access_fingerprint(
                registration_copy
            )
            if locator_fingerprint != verified_pack._locator_bound_fingerprint:
                raise ValueError(
                    f"external capability pack lock registration drift: {capability_id}"
                )
            verified[capability_id] = _freeze(
                {
                    **registration_copy,
                    "sourceKind": "EXTERNAL_CAPABILITY_PACK",
                    "registrationFingerprint": locator_fingerprint,
                    "manifest": _thaw(verified_pack.manifest),
                }
            )
            continue
        entry = by_version.get((capability_id, item["resolvedVersion"]))
        if entry is None:
            raise ValueError(
                "capability lock references missing version: "
                f"{capability_id}@{item['resolvedVersion']}"
            )
        if entry["contentHash"] != item["contentHash"]:
            raise ValueError(f"capability lock content hash drift: {capability_id}")
        if (
            entry["lifecycle"] in {"DEPRECATED", "RETIRED"}
            or entry["validity"] != "VALID"
        ):
            raise ValueError(f"capability lock references unusable capability: {capability_id}")
        frozen_entry = _freeze(entry)
        verified[capability_id] = frozen_entry
        internal_entries[capability_id] = frozen_entry

    ordered_pack_keys = [
        _pack_key_witness(external_by_id[capability_id].key)
        for capability_id in sorted(external_by_id)
    ]
    project_identity = project.resolve(strict=True)
    key_record = {
        "projectRoot": str(project_identity),
        "lock": {"sha256": lock_bytes_digest, "value": lock},
        "state": {"sha256": state_bytes_digest, "value": state},
        "binding": {"sha256": binding_bytes_digest, "value": binding},
        "profiles": profiles,
        "resolvedBecause": reasons,
        "designRegistryInputs": registry_inputs,
        "designRegistry": registry,
        "activeCatalog": catalog,
        "activeInternalCapabilityIds": sorted(active_internal_ids),
        "internalEntries": internal_entries,
        "internalExternalCollisions": collisions,
        "externalPackKeys": ordered_pack_keys,
    }
    key = LockVerificationKey(
        project_root=project_identity,
        digest="sha256:" + sha256_bytes(canonical_json_bytes(_thaw(key_record))),
    )
    context = VerifiedLockContext(
        key=key,
        lock=_freeze(lock),
        entries=_freeze(verified),
        verified_packs=_freeze(external_by_id),
        _session_token=verification_session._token,
    )
    return _publish_verified_lock_context(verification_session, context)


def verify_capability_lock_context(
    repository_root: Path,
    project_root: Path,
    *,
    verification_session: CapabilityVerificationSession,
) -> VerifiedLockContext:
    root = Path(repository_root)
    project = Path(project_root)
    try:
        declared_lock = load_capability_lock(root, project)
        external_ids = {
            item["capabilityId"]
            for item in declared_lock["capabilities"]
            if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK"
        }
        with verification_session._operation_lease(root, external_ids):
            return _verify_capability_lock_context(
                root,
                project,
                verification_session=verification_session,
            )
    except BaseException as exc:
        verification_session._poison(exc)
        raise


def verify_capability_lock(
    repository_root: Path,
    project_root: Path,
    *,
    verification_session: CapabilityVerificationSession | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    root = Path(repository_root)
    project = Path(project_root)
    if verification_session is None:
        declared_lock = load_capability_lock(root, project)
        external_ids = {
            item["capabilityId"]
            for item in declared_lock["capabilities"]
            if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK"
        }
        with CapabilityVerificationSession(
            root,
            allowed_capability_ids=external_ids,
        ) as private_session:
            context = verify_capability_lock_context(
                root,
                project,
                verification_session=private_session,
            )
            return context.public_result()
    return verify_capability_lock_context(
        root,
        project,
        verification_session=verification_session,
    ).public_result()
