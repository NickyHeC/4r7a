"""Slack Web API client for operations platform agents (read + thread replies).

Human-facing notifications still go through ``Notifier`` / ``Signal``.
Thread replies from ``linear_completed`` are system propagation, not alerts.

Token resolution: ``SLACK_WIKI_BOT_TOKEN`` (required for company-brain), with
legacy fallback to ``SLACK_BOT_TOKEN``. Optional ``SLACK_WEAVE_BOT_TOKEN`` for
the Weave app (Session 7+).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from datetime import datetime
from typing import Any


class SlackClientError(RuntimeError):
    pass


def wiki_bot_token() -> str:
    token = os.getenv("SLACK_WIKI_BOT_TOKEN", "").strip()
    if not token:
        token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    if not token:
        raise SlackClientError(
            "SLACK_WIKI_BOT_TOKEN not set — see project_install.md (legacy: SLACK_BOT_TOKEN)"
        )
    return token


def weave_bot_token() -> str:
    return os.getenv("SLACK_WEAVE_BOT_TOKEN", "").strip()


def bot_token() -> str:
    """Default wiki bot token for platform agents and notifiers."""
    return wiki_bot_token()


def client(*, app: str = "wiki") -> Any:
    from slack_sdk import WebClient

    if app == "weave":
        token = weave_bot_token()
        if not token:
            raise SlackClientError("SLACK_WEAVE_BOT_TOKEN not set")
        return WebClient(token=token)
    return WebClient(token=wiki_bot_token())


def slack_is_configured() -> bool:
    return bool(
        os.getenv("SLACK_WIKI_BOT_TOKEN", "").strip() or os.getenv("SLACK_BOT_TOKEN", "").strip()
    )


def weave_is_configured() -> bool:
    return bool(os.getenv("SLACK_WEAVE_BOT_TOKEN", "").strip())


def wiki_app_token() -> str:
    return os.getenv("SLACK_WIKI_APP_TOKEN", "").strip()


def wiki_signing_secret() -> str:
    return os.getenv("SLACK_WIKI_SIGNING_SECRET", "").strip()


def weave_app_token() -> str:
    return os.getenv("SLACK_WEAVE_APP_TOKEN", "").strip()


def weave_signing_secret() -> str:
    return os.getenv("SLACK_WEAVE_SIGNING_SECRET", "").strip()


def weave_socket_mode_configured() -> bool:
    return weave_is_configured() and bool(weave_app_token())


def socket_mode_configured() -> bool:
    return slack_is_configured() and bool(wiki_app_token())


def verify_http_signature(
    body: bytes,
    timestamp: str,
    signature: str,
    *,
    signing_secret: str | None = None,
) -> bool:
    secret = (signing_secret or wiki_signing_secret()).strip()
    if not secret or not signature:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts) > 60 * 5:
        return False
    base = f"v0:{timestamp}:{body.decode('utf-8')}"
    digest = hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"v0={digest}", signature)


def list_channels(*, types: str = "public_channel,private_channel") -> list[dict[str, Any]]:
    """Paginate ``conversations.list``."""
    from slack_sdk.errors import SlackApiError

    channels: list[dict[str, Any]] = []
    cursor: str | None = None
    try:
        while True:
            kwargs: dict[str, Any] = {"types": types, "limit": 200}
            if cursor:
                kwargs["cursor"] = cursor
            resp = client().conversations_list(**kwargs)
            channels.extend(resp.get("channels") or [])
            cursor = (resp.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
    except SlackApiError as exc:
        raise SlackClientError(f"conversations.list failed: {exc}") from exc
    return channels


def join_channel(channel_id: str) -> bool:
    from slack_sdk.errors import SlackApiError

    try:
        client().conversations_join(channel=channel_id)
        return True
    except SlackApiError:
        return False


def join_internal_channels() -> dict[str, int]:
    """Join all non–Slack Connect channels the bot is not already in."""
    joined = 0
    skipped = 0
    for ch in list_channels():
        if ch.get("is_ext_shared") or ch.get("is_member"):
            skipped += 1
            continue
        if join_channel(str(ch.get("id") or "")):
            joined += 1
    return {"joined": joined, "skipped": skipped}


def auth_test() -> dict[str, Any]:
    from slack_sdk.errors import SlackApiError

    try:
        return dict(client().auth_test())
    except SlackApiError as exc:
        raise SlackClientError(f"auth.test failed: {exc}") from exc


def bot_user_id() -> str:
    return str(auth_test().get("user_id") or "")


def channel_label(channel_id: str, *, name: str | None = None) -> str:
    if name:
        return f"#{name.lstrip('#')}"
    if channel_id.startswith("C"):
        return channel_id
    return channel_id


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
    channel_id = resolve_channel_id(channel)
    return fetch_channel_messages_by_id(
        channel_id,
        oldest=oldest,
        latest=latest,
        limit=limit,
    )


def fetch_channel_messages_by_id(
    channel_id: str,
    *,
    oldest: float | None = None,
    latest: float | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    from slack_sdk.errors import SlackApiError

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


def post_thread_reply(
    channel: str,
    thread_ts: str,
    text: str,
    *,
    app: str = "wiki",
) -> str | None:
    """Post a reply in a thread (system propagation — not human notifications)."""
    from slack_sdk.errors import SlackApiError

    channel_id = resolve_channel_id(channel)
    try:
        resp = client(app=app).chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=text,
        )
        return resp.get("ts")
    except SlackApiError as exc:
        raise SlackClientError(f"chat.postMessage failed: {exc}") from exc


def permalink(channel: str, message_ts: str, *, app: str = "wiki") -> str:
    from slack_sdk.errors import SlackApiError

    channel_id = resolve_channel_id(channel)
    try:
        resp = client(app=app).chat_getPermalink(channel=channel_id, message_ts=message_ts)
        return str(resp.get("permalink") or "")
    except SlackApiError:
        return ""


def datetime_to_slack_ts(dt: datetime) -> float:
    return dt.timestamp()
