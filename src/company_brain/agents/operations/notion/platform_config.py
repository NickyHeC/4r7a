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


def stub_ttl_days(*, config_dir: Path | None = None) -> int:
    return int(_notion_platform_cfg(config_dir).get("stub_ttl_days") or 7)


def archive_idle_days(*, config_dir: Path | None = None) -> int:
    return int(_notion_platform_cfg(config_dir).get("archive_idle_days") or 30)


def stale_idle_days(*, config_dir: Path | None = None) -> int:
    return int(_notion_platform_cfg(config_dir).get("stale_idle_days") or 90)


def _orphan_cfg(*, config_dir: Path | None = None) -> dict[str, Any]:
    block = _notion_platform_cfg(config_dir).get("orphan_discovery") or {}
    return block if isinstance(block, dict) else {}


def orphan_discovery_enabled(*, config_dir: Path | None = None) -> bool:
    return bool(_orphan_cfg(config_dir=config_dir).get("enabled", True))


def orphan_discovery_admin_channel(*, config_dir: Path | None = None) -> str:
    from company_brain.agents.operations.shared.gmail_config import slack_cfg

    channel = str(_orphan_cfg(config_dir=config_dir).get("admin_channel") or "").strip()
    return channel or str(slack_cfg().get("ingest_channel") or "#ingest")
