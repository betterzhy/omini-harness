from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def capability_content_hash(asset: dict[str, Any], content: str) -> str:
    payload = {"asset": asset, "content": content.replace("\r\n", "\n")}
    return sha256_bytes(canonical_json_bytes(payload))
