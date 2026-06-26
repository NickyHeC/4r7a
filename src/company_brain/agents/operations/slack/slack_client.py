"""Slack Web API client for operations platform agents (read + thread replies).

Human-facing notifications still go through ``Notifier`` / ``Signal``.
Thread replies from ``linear_completed`` are system propagation, not alerts.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any


class SlackClientError(RuntimeError):
    pass


def bot_token() -> str:
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    if not token:
        raise SlackClientError("SLACK_BOT_TOKEN not set — see project_install.md")
    return token


def client() -> Any:
    from slack_sdk import WebClient

    return WebClient(token=bot_token())


def slack_is_configured() -> bool:
    return bool(os.getenv("SLACK_BOT_TOKEN", "").strip())


def resolve_channel_id(channel: str) -> str:
    """Resolve ``#name`` or channel ID to a channel ID."""
    from slack_sdk.errors import SlackApiError

    ref = (channel or "").strip()
    if not ref:
        raise SlackClientError("channel required")
    if ref.startswith("C") and len(ref) >= 9:
        return ref
    name = ref.lstrip("#")
    try:
        resp = client().conversations_list(types="public_channel,private_channel", limit=200)
        for ch in resp.get("channels") or []:
            if ch.get("name") == name:
                return ch["id"]
    except SlackApiError as exc:
        raise SlackClientError(f"conversations.list failed: {exc}") from exc
    raise SlackClientError(f"Slack channel '{channel}' not found")


def fetch_channel_messages(
    channel: str,
    *,
    oldest: float | None = None,
    latest: float | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return channel messages (includes thread roots)."""
    from slack_sdk.errors import SlackApiError

    channel_id = resolve_channel_id(channel)
    kwargs: dict[str, Any] = {"channel": channel_id, "limit": limit}
    if oldest is not None:
        kwargs["oldest"] = str(oldest)
    if latest is not None:
        kwargs["latest"] = str(latest)
    try:
        resp = client().conversations_history(**kwargs)
        return list(resp.get("messages") or [])
    except SlackApiError as exc:
        raise SlackClientError(f"conversations.history failed: {exc}") from exc


def fetch_thread_replies(channel: str, thread_ts: str) -> list[dict[str, Any]]:
    """Return all messages in a thread (including root)."""
    from slack_sdk.errors import SlackApiError

    channel_id = resolve_channel_id(channel)
    try:
        resp = client().conversations_replies(channel=channel_id, ts=thread_ts)
        return list(resp.get("messages") or [])
    except SlackApiError as exc:
        raise SlackClientError(f"conversations.replies failed: {exc}") from exc


def post_thread_reply(channel: str, thread_ts: str, text: str) -> str | None:
    """Post a reply in a thread (system propagation — not human notifications)."""
    from slack_sdk.errors import SlackApiError

    channel_id = resolve_channel_id(channel)
    try:
        resp = client().chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=text)
        return resp.get("ts")
    except SlackApiError as exc:
        raise SlackClientError(f"chat.postMessage failed: {exc}") from exc


def permalink(channel: str, message_ts: str) -> str:
    from slack_sdk.errors import SlackApiError

    channel_id = resolve_channel_id(channel)
    try:
        resp = client().chat_getPermalink(channel=channel_id, message_ts=message_ts)
        return str(resp.get("permalink") or "")
    except SlackApiError:
        return ""


def datetime_to_slack_ts(dt: datetime) -> float:
    return dt.timestamp()
