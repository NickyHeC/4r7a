"""Notification helpers for operations agents.

Per the **"detect everything, notify selectively"** rule, agents never post to
Slack directly — every human-facing message goes through a severity-gated
``company_brain.notify.Notifier``. These helpers return a Notifier already bound
to the right operations Slack channel; the Slack SDK is only the transport.
"""

from __future__ import annotations

import os
from typing import Any

from company_brain.agents.operations.shared.gmail_config import slack_cfg
from company_brain.notify import ACTIONABLE, Notifier, Signal


class _SlackChannel:
    """Slack transport: a channel-bound ``post(text)`` callable for the Notifier."""

    def __init__(self, channel: str, token: str | None = None):
        self.channel = channel
        if token:
            self._token = token
        else:
            self._token = (
                os.getenv("SLACK_WIKI_BOT_TOKEN", "").strip()
                or os.getenv("SLACK_BOT_TOKEN", "").strip()
            )
        self._client = None

    @property
    def client(self) -> Any:
        if self._client is None:
            from slack_sdk import WebClient

            if not self._token:
                raise RuntimeError("SLACK_WIKI_BOT_TOKEN not set — see .env")
            self._client = WebClient(token=self._token)
        return self._client

    def post(self, text: str) -> str | None:
        from slack_sdk.errors import SlackApiError

        try:
            resp = self.client.chat_postMessage(channel=self.channel, text=text)
            return resp.get("ts")
        except SlackApiError:
            return None


def channel_notifier(channel: str) -> Notifier:
    """Severity-gated Notifier that posts to a specific operations Slack channel."""
    return Notifier(channel_post=_SlackChannel(channel).post)


class _ThreadReply:
    """Slack transport: a thread-bound reply callable for request/response Notifiers."""

    def __init__(self, channel: str, thread_ts: str, *, app: str = "wiki"):
        self.channel = channel
        self.thread_ts = thread_ts
        self.app = app
        self.last_ts: str | None = None

    def post(self, text: str) -> str | None:
        from company_brain.agents.operations.slack import slack_client

        try:
            self.last_ts = slack_client.post_thread_reply(
                self.channel, self.thread_ts, text, app=self.app
            )
        except slack_client.SlackClientError:
            self.last_ts = None
        return self.last_ts


def reply_in_thread(
    channel: str,
    thread_ts: str,
    text: str,
    *,
    severity: str = ACTIONABLE,
    app: str = "wiki",
    silent: bool = False,
) -> tuple[bool, str | None]:
    """Route a Slack thread reply through the severity gate.

    Request/response replies (a human invoked the agent) default to ``ACTIONABLE``
    so they are delivered; returns ``(delivered, ts)``. Keeps all Slack posting in
    the notifier transport layer per the notify rule.
    """
    transport = _ThreadReply(channel, thread_ts, app=app)
    notifier = Notifier(channel_post=transport.post)
    delivered = notifier.emit(Signal(text=text, severity=severity, silent=silent))
    return delivered, transport.last_ts


def ingest_notifier() -> Notifier:
    return channel_notifier(slack_cfg().get("ingest_channel") or "#ingest")


def customer_support_notifier() -> Notifier:
    return channel_notifier(slack_cfg().get("customer_support_channel") or "#customer-support")


def events_notifier() -> Notifier:
    return channel_notifier(slack_cfg().get("events_channel") or "#events")


def growth_notifier() -> Notifier:
    return channel_notifier(slack_cfg().get("growth_channel") or "#growth")


def daily_agenda_notifier(slack_user_id: str) -> Notifier:
    """DM notifier for the optional daily agenda agent."""
    return channel_notifier(slack_user_id)
