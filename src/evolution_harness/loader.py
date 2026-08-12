from __future__ import annotations

from pathlib import Path

import yaml

from .hashing import capability_content_hash
from .models import CapabilityAsset


def load_capabilities(repository_root: Path) -> list[CapabilityAsset]:
    root = Path(repository_root)
    capabilities: list[CapabilityAsset] = []
    capability_root = root / "design" / "capabilities"
    if not capability_root.exists():
        return capabilities
    for asset_path in sorted(capability_root.rglob("asset.yaml")):
        asset = yaml.safe_load(asset_path.read_text(encoding="utf-8")) or {}
        content_name = asset.get("contentFile", "content.md")
        content_path = asset_path.parent / content_name
        content = content_path.read_text(encoding="utf-8") if content_path.exists() else ""
        capabilities.append(
            CapabilityAsset(
                asset_path=asset_path,
                content_path=content_path,
                asset=asset,
                content=content,
                content_hash=capability_content_hash(asset, content),
            )
        )
    return capabilities
