"""Slack channel registry (``config/slack_channels.json``)."""

from __future__ import annotations

import json
from typing import Any

from company_brain.config import CONFIG_DIR

CHANNELS_FILE = CONFIG_DIR / "slack_channels.json"


def load_channels_registry() -> dict[str, Any]:
    if not CHANNELS_FILE.exists():
        return {"version": 1, "channels": {}}
    try:
        data = json.loads(CHANNELS_FILE.read_text()) or {}
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "channels": {}}
    data.setdefault("version", 1)
    data.setdefault("channels", {})
    return data


def save_channels_registry(data: dict[str, Any]) -> None:
    data.setdefault("version", 1)
    data.setdefault("channels", {})
    CHANNELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHANNELS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(CHANNELS_FILE)


def get_channel(channel_id: str) -> dict[str, Any] | None:
    entry = (load_channels_registry().get("channels") or {}).get(channel_id)
    return dict(entry) if isinstance(entry, dict) else None


def ingest_mode(channel_id: str) -> str:
    """Return ``hot``, ``cold``, or ``out_of_scope`` (default ``hot``)."""
    entry = get_channel(channel_id)
    if not entry:
        return "hot"
    mode = str(entry.get("ingest_mode") or "hot").lower()
    if mode in {"hot", "cold", "out_of_scope"}:
        return mode
    return "hot"


def is_out_of_scope(channel_id: str) -> bool:
    return ingest_mode(channel_id) == "out_of_scope"
