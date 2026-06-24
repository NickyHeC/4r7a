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
from company_brain.notify import Notifier


class _SlackChannel:
    """Slack transport: a channel-bound ``post(text)`` callable for the Notifier."""

    def __init__(self, channel: str, token: str | None = None):
        self.channel = channel
        self._token = token or os.getenv("SLACK_BOT_TOKEN", "")
        self._client = None

    @property
    def client(self) -> Any:
        if self._client is None:
            from slack_sdk import WebClient
            if not self._token:
                raise RuntimeError("SLACK_BOT_TOKEN not set — see .env")
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


def ingest_notifier() -> Notifier:
    return channel_notifier(slack_cfg().get("ingest_channel") or "#ingest")


def customer_support_notifier() -> Notifier:
    return channel_notifier(slack_cfg().get("customer_support_channel") or "#customer-support")


def events_notifier() -> Notifier:
    return channel_notifier(slack_cfg().get("events_channel") or "#events")


def growth_notifier() -> Notifier:
    return channel_notifier(slack_cfg().get("growth_channel") or "#growth")


def partnership_digest_notifier() -> Notifier:
    user = (slack_cfg().get("partnership_digest_user") or "").strip()
    channel = user or slack_cfg().get("partnership_digest_channel") or "#partnerships"
    return channel_notifier(channel)


def daily_agenda_notifier(slack_user_id: str) -> Notifier:
    """DM notifier for the optional daily agenda agent."""
    return channel_notifier(slack_user_id)
