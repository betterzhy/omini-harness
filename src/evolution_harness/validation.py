from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .governance import validate_promotion_authority
from .identity import IdentityError, VersionError, parse_capability_id, validate_semver
from .loader import load_capabilities
from .models import CapabilityAsset, ValidationIssue, ValidationReport
from .relations import validate_relationships
from .schema import SchemaStore, SchemaValidationError


def validate_repository(repository_root: Path) -> ValidationReport:
    root = Path(repository_root)
    store = SchemaStore(root)
    capabilities = load_capabilities(root)
    issues: list[ValidationIssue] = []

    seen: dict[tuple[str, str], CapabilityAsset] = {}
    by_id: dict[str, list[CapabilityAsset]] = defaultdict(list)

    for capability in capabilities:
        asset = capability.asset
        try:
            identity = parse_capability_id(asset.get("id", ""))
            if identity.kind.upper() != asset.get("kind"):
                issues.append(
                    ValidationIssue(
                        "IDENTITY_KIND_MISMATCH",
                        f"identity kind {identity.kind} does not match asset kind {asset.get('kind')}",
                        str(capability.asset_path),
                    )
                )
        except IdentityError as exc:
            issues.append(ValidationIssue("IDENTITY_INVALID", str(exc), str(capability.asset_path)))
        try:
            validate_semver(asset.get("version", ""))
        except VersionError as exc:
            issues.append(ValidationIssue("VERSION_INVALID", str(exc), str(capability.asset_path)))

        key = (asset.get("id", ""), asset.get("version", ""))
        if key in seen:
            issues.append(ValidationIssue("DUPLICATE_ID_VERSION", f"duplicate canonical id/version {key[0]}@{key[1]}", str(capability.asset_path)))
        else:
            seen[key] = capability
        by_id[asset.get("id", "")].append(capability)

        expected_kind = None
        try:
            expected_kind = parse_capability_id(asset.get("id", "")).kind
        except IdentityError:
            pass
        if expected_kind:
            schema_path = f"design/schemas/{expected_kind}.schema.json"
            try:
                store.validate(schema_path, asset)
            except (SchemaValidationError, FileNotFoundError) as exc:
                issues.append(ValidationIssue("SCHEMA_INVALID", str(exc), str(capability.asset_path)))
        if not capability.content_path.exists():
            issues.append(ValidationIssue("CONTENT_MISSING", f"content file missing: {capability.content_path}", str(capability.asset_path)))

    issues.extend(validate_relationships(capabilities))
    issues.extend(validate_promotion_authority(root, capabilities))
    issues.sort(key=lambda issue: (issue.code, issue.path or "", issue.message))
    return ValidationReport(tuple(issues))
