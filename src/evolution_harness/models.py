from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CapabilityAsset:
    asset_path: Path
    content_path: Path
    asset: dict[str, Any]
    content: str
    content_hash: str

    @property
    def id(self) -> str:
        return self.asset["id"]

    @property
    def version(self) -> str:
        return self.asset["version"]

    @property
    def kind(self) -> str:
        return self.asset["kind"]


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues
