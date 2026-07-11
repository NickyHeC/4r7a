"""Discord REST + Gateway helpers for growth platform agents (read-only).

Human-facing notifications go through ``Notifier`` / ``Signal`` — this client
never posts to Discord channels.

Token: ``DISCORD_BOT_TOKEN`` (required when Discord is connected).
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

import requests

API_BASE = "https://discord.com/api/v10"
GATEWAY_VERSION = 10


class DiscordClientError(RuntimeError):
    pass


def bot_token() -> str:
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise DiscordClientError("DISCORD_BOT_TOKEN not set — see project_install.md")
    return token


def discord_is_configured() -> bool:
    return bool(os.getenv("DISCORD_BOT_TOKEN", "").strip())


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bot {bot_token()}",
        "User-Agent": "company-brain-discord/1.0",
    }


def api_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Any:
    url = f"{API_BASE}{path}"
    try:
        resp = requests.request(
            method.upper(),
            url,
            headers=_headers(),
            params=params,
            json=json_body,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise DiscordClientError(f"Discord API request failed: {exc}") from exc
    if resp.status_code == 429:
        retry = float((resp.json() or {}).get("retry_after", 1.0))
        time.sleep(min(retry, 5.0))
        return api_request(method, path, params=params, json_body=json_body, timeout=timeout)
    if resp.status_code >= 400:
        raise DiscordClientError(
            f"Discord API {method} {path} failed ({resp.status_code}): {resp.text[:300]}"
        )
    if resp.status_code == 204 or not resp.content:
        return None
    return resp.json()


def get_bot_user() -> dict[str, Any]:
    data = api_request("GET", "/users/@me")
    return dict(data or {})


def bot_user_id() -> str:
    return str(get_bot_user().get("id") or "")


def get_gateway_url() -> str:
    data = api_request("GET", "/gateway/bot")
    url = str((data or {}).get("url") or "wss://gateway.discord.gg")
    return f"{url}/?v={GATEWAY_VERSION}&encoding=json"


def list_guild_channels(guild_id: str) -> list[dict[str, Any]]:
    data = api_request("GET", f"/guilds/{guild_id}/channels")
    return list(data or [])


def get_channel(channel_id: str) -> dict[str, Any]:
    data = api_request("GET", f"/channels/{channel_id}")
    return dict(data or {})


def fetch_channel_messages(
    channel_id: str,
    *,
    before: str | None = None,
    after: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": min(max(limit, 1), 100)}
    if before:
        params["before"] = before
    if after:
        params["after"] = after
    data = api_request("GET", f"/channels/{channel_id}/messages", params=params)
    return list(data or [])


def fetch_messages_since(
    channel_id: str,
    *,
    oldest: datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return messages in a channel, optionally stopping before ``oldest``."""
    batch = fetch_channel_messages(channel_id, limit=limit)
    if not batch:
        return []
    if oldest is None:
        return batch
    cutoff = oldest.timestamp()
    out: list[dict[str, Any]] = []
    for msg in batch:
        ts = _message_timestamp(msg)
        if ts and ts < cutoff:
            break
        out.append(msg)
    return out


def message_permalink(guild_id: str, channel_id: str, message_id: str) -> str:
    gid = (guild_id or "").strip()
    if not gid:
        return ""
    return f"https://discord.com/channels/{gid}/{channel_id}/{message_id}"


def channel_label(channel_id: str, *, name: str | None = None) -> str:
    if name:
        return f"#{name.lstrip('#')}"
    return channel_id


def is_thread_channel(channel_type: int | None) -> bool:
    from company_brain.agents.growth.discord import discord_config as cfg

    return int(channel_type or -1) in cfg.THREAD_CHANNEL_TYPES


def conversation_ids(
    message: dict[str, Any],
    *,
    channel_type: int | None = None,
    parent_id: str | None = None,
) -> tuple[str, str, str]:
    """Return ``(routing_channel_id, thread_id, message_id)`` for routing."""
    channel_id = str(message.get("channel_id") or "")
    message_id = str(message.get("id") or "")

    ch = message.get("channel") or {}
    if channel_type is None:
        channel_type = int(ch.get("type", -1))
    if parent_id is None and ch.get("parent_id"):
        parent_id = str(ch.get("parent_id"))

    if is_thread_channel(channel_type):
        parent_channel_id = str(parent_id or channel_id)
        return parent_channel_id, channel_id, message_id

    parent_channel_id = channel_id
    ref = message.get("message_reference") or {}
    if ref.get("message_id"):
        thread_id = str(ref["message_id"])
    else:
        thread_id = message_id
    return parent_channel_id, thread_id, message_id


def _message_timestamp(message: dict[str, Any]) -> float | None:
    raw = message.get("timestamp")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def datetime_to_snowflake_after(dt: datetime) -> str | None:
    """Approximate snowflake lower bound for ``after`` query param."""
    ms = int(dt.timestamp() * 1000)
    snowflake = (ms - 1420070400000) << 22
    return str(snowflake) if snowflake > 0 else None
