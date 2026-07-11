"""Discord channel registry (``config/discord_channels.json``)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.growth.discord import discord_config as cfg
from company_brain.config import CONFIG_DIR

CHANNELS_FILE = CONFIG_DIR / "discord_channels.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_channels_registry() -> dict[str, Any]:
    if not CHANNELS_FILE.exists():
        return {"version": 1, "guild_id": cfg.guild_id(), "channels": {}}
    try:
        data = json.loads(CHANNELS_FILE.read_text()) or {}
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "guild_id": cfg.guild_id(), "channels": {}}
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
    data["guild_id"] = cfg.guild_id() or data.get("guild_id") or ""
    channels = data.setdefault("channels", {})
    entry = dict(channels.get(channel_id) or {})
    entry.update(fields)
    entry.setdefault("ingest_mode", "hot")
    entry["last_activity_at"] = _utc_now()
    channels[channel_id] = entry
    save_channels_registry(data)
    return entry


def channel_name(channel_id: str) -> str:
    entry = get_channel(channel_id) or {}
    return str(entry.get("name") or channel_id)


def ingest_mode(channel_id: str) -> str:
    entry = get_channel(channel_id) or {}
    mode = str(entry.get("ingest_mode") or "hot").lower()
    if mode in {"hot", "cold", "out_of_scope"}:
        return mode
    return "hot"


def is_out_of_scope(channel_id: str) -> bool:
    if ingest_mode(channel_id) == "out_of_scope":
        return True
    name = channel_name(channel_id).lower().lstrip("#")
    for excluded in cfg.exclude_channels():
        if excluded == channel_id.lower() or excluded == name:
            return True
    return False


def sync_from_discord_api(channels: list[dict[str, Any]]) -> int:
    """Merge Discord API channel metadata into the registry."""
    count = 0
    for ch in channels:
        channel_id = str(ch.get("id") or "")
        if not channel_id:
            continue
        ch_type = int(ch.get("type", 0))
        if ch_type not in {
            cfg.CHANNEL_GUILD_TEXT,
            cfg.CHANNEL_ANNOUNCEMENT,
            cfg.CHANNEL_PUBLIC_THREAD,
            cfg.CHANNEL_PRIVATE_THREAD,
            cfg.CHANNEL_GUILD_FORUM,
        }:
            continue
        existing = get_channel(channel_id) or {}
        name = str(ch.get("name") or existing.get("name") or channel_id)
        excluded = any(
            ex == channel_id.lower() or ex == name.lower().lstrip("#")
            for ex in cfg.exclude_channels()
        )
        upsert_channel(
            channel_id,
            name=name,
            type=ch_type,
            parent_id=str(ch.get("parent_id") or ""),
            ingest_mode="out_of_scope" if excluded else existing.get("ingest_mode", "hot"),
        )
        count += 1
    return count


def list_text_channels() -> list[dict[str, Any]]:
    """Return ingest-eligible guild text channels from the registry."""
    rows: list[dict[str, Any]] = []
    for channel_id, entry in sorted((load_channels_registry().get("channels") or {}).items()):
        if not isinstance(entry, dict):
            continue
        ch_type = int(entry.get("type", cfg.CHANNEL_GUILD_TEXT))
        if ch_type not in {
            cfg.CHANNEL_GUILD_TEXT,
            cfg.CHANNEL_ANNOUNCEMENT,
            cfg.CHANNEL_GUILD_FORUM,
        }:
            continue
        if is_out_of_scope(channel_id):
            continue
        rows.append({"id": channel_id, **entry})
    return rows


def list_channels_summary() -> list[dict[str, Any]]:
    data = load_channels_registry().get("channels") or {}
    rows: list[dict[str, Any]] = []
    for channel_id, entry in sorted(data.items()):
        if not isinstance(entry, dict):
            continue
        rows.append({"id": channel_id, **entry})
    return rows
