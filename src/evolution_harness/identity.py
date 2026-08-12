from __future__ import annotations

import re
from dataclasses import dataclass

_ALLOWED_KINDS = {"principle", "framework", "skill", "workflow"}
_COMPONENT = r"[a-z0-9][a-z0-9._-]*"
_ID_RE = re.compile(rf"^(?P<kind>{_COMPONENT}):(?P<namespace>{_COMPONENT}):(?P<name>{_COMPONENT})$")
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class IdentityError(ValueError):
    pass


class VersionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CapabilityIdentity:
    kind: str
    namespace: str
    name: str


def parse_capability_id(value: str) -> CapabilityIdentity:
    match = _ID_RE.fullmatch(value or "")
    if not match:
        raise IdentityError(f"invalid capability identity: {value!r}")
    kind = match.group("kind")
    if kind not in _ALLOWED_KINDS:
        raise IdentityError(f"unsupported capability kind: {kind}")
    return CapabilityIdentity(kind=kind, namespace=match.group("namespace"), name=match.group("name"))


def validate_semver(value: str) -> str:
    if not _SEMVER_RE.fullmatch(value or ""):
        raise VersionError(f"invalid semantic version: {value!r}")
    return value
