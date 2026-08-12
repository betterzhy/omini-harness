from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


_MARKDOWN_KV = re.compile(r"^([A-Za-z][A-Za-z0-9_.-]*)\s*(?:=|:|：)\s*(.*?)\s*$")


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _nested(value: Any, dotted: str) -> list[str]:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return []
        current = current[part]
    return [_stringify(current)]


def _markdown_values(text: str, keys: list[str]) -> dict[str, list[str]]:
    wanted = set(keys)
    found = {key: [] for key in keys}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(">"):
            line = line[1:].strip()
        line = line.replace("**", "").replace("<br>", "").strip()
        match = _MARKDOWN_KV.match(line)
        if not match or match.group(1) not in wanted:
            continue
        value = match.group(2).strip().strip("`").strip()
        if value not in found[match.group(1)]:
            found[match.group(1)].append(value)
    return found


def extract_values_bytes(data: bytes, source_format: str, keys: list[str]) -> dict[str, list[str]]:
    text = data.decode("utf-8")
    if source_format == "MARKDOWN_KV":
        return _markdown_values(text, keys)
    if source_format == "YAML":
        value = yaml.safe_load(text) or {}
    elif source_format == "JSON":
        value = json.loads(text)
    else:
        raise ValueError(f"unsupported authority source format: {source_format}")
    return {key: _nested(value, key) for key in keys}


def extract_values(path: Path, source_format: str, keys: list[str]) -> dict[str, list[str]]:
    return extract_values_bytes(path.read_bytes(), source_format, keys)
