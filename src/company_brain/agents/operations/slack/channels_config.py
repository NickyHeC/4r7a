"""Slack channel registry (``config/slack_channels.json``)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from company_brain.config import CONFIG_DIR

CHANNELS_FILE = CONFIG_DIR / "slack_channels.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def upsert_channel(channel_id: str, **fields: Any) -> dict[str, Any]:
    data = load_channels_registry()
    channels = data.setdefault("channels", {})
    entry = dict(channels.get(channel_id) or {})
    entry.update(fields)
    entry.setdefault("ingest_mode", "hot")
    entry["last_activity_at"] = _utc_now()
    channels[channel_id] = entry
    save_channels_registry(data)
    return entry


def set_ingest_mode(channel_id: str, mode: str) -> dict[str, Any]:
    normalized = mode.strip().lower()
    if normalized not in {"hot", "cold", "out_of_scope"}:
        raise ValueError(f"invalid ingest_mode: {mode}")
    return upsert_channel(channel_id, ingest_mode=normalized)


def enable_connect_channel(channel_id: str, *, name: str | None = None) -> dict[str, Any]:
    return upsert_channel(
        channel_id,
        name=name or channel_id,
        is_connect=True,
        customer_support=True,
        ask_wiki_allowed=False,
        ingest_mode="hot",
    )


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


def is_connect_channel(channel_id: str) -> bool:
    entry = get_channel(channel_id) or {}
    return bool(entry.get("is_connect"))


def channel_name(channel_id: str) -> str:
    entry = get_channel(channel_id) or {}
    return str(entry.get("name") or channel_id)


def sync_from_slack_api(channels: list[dict[str, Any]]) -> int:
    """Merge Slack API channel metadata into the registry."""
    count = 0
    for ch in channels:
        channel_id = str(ch.get("id") or "")
        if not channel_id:
            continue
        existing = get_channel(channel_id) or {}
        upsert_channel(
            channel_id,
            name=ch.get("name") or existing.get("name") or channel_id,
            is_connect=bool(ch.get("is_ext_shared")),
            is_private=bool(ch.get("is_private")),
            is_member=bool(ch.get("is_member")),
            ingest_mode=existing.get("ingest_mode")
            or ("hot" if not ch.get("is_ext_shared") else "cold"),
            customer_support=existing.get("customer_support", bool(ch.get("is_ext_shared"))),
            ask_wiki_allowed=existing.get("ask_wiki_allowed", not ch.get("is_ext_shared")),
        )
        count += 1
    return count


def list_channels_summary() -> list[dict[str, Any]]:
    data = load_channels_registry().get("channels") or {}
    rows: list[dict[str, Any]] = []
    for channel_id, entry in sorted(data.items()):
        if not isinstance(entry, dict):
            continue
        rows.append({"id": channel_id, **entry})
    return rows
