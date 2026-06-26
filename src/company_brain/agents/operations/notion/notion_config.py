"""Operations Notion platform settings from ``config/operations.yaml``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from company_brain.config import CONFIG_DIR, _load_yaml


def _notion_platform_cfg(config_dir: Path | None = None) -> dict[str, Any]:
    path = (config_dir or CONFIG_DIR) / "operations.yaml"
    data = _load_yaml(path) or {}
    block = data.get("notion_platform") or {}
    return block if isinstance(block, dict) else {}


def poll_interval_minutes(*, config_dir: Path | None = None) -> int:
    return int(_notion_platform_cfg(config_dir).get("poll_interval_minutes") or 30)
