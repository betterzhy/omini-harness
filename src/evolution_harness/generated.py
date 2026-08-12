from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .hashing import sha256_bytes


@dataclass(frozen=True, slots=True)
class GeneratedCheck:
    fresh: bool
    expected_hash: str
    actual_hash: str | None
    reason: str | None = None


def deterministic_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_generated_json(path: Path, value: Any) -> bytes:
    data = deterministic_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def check_generated_file(path: Path, expected: bytes) -> GeneratedCheck:
    expected_hash = sha256_bytes(expected)
    if not path.exists():
        return GeneratedCheck(False, expected_hash, None, "missing")
    actual = path.read_bytes()
    actual_hash = sha256_bytes(actual)
    if actual != expected:
        return GeneratedCheck(False, expected_hash, actual_hash, "drift")
    return GeneratedCheck(True, expected_hash, actual_hash)
