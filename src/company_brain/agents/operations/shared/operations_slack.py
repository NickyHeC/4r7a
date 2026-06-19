"""Slack helper for operations agents."""

from __future__ import annotations

import os
from typing import Any

from company_brain.agents.operations.shared.gmail_config import slack_cfg


class OperationsSlack:
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


def ingest_slack() -> OperationsSlack:
    channel = slack_cfg().get("ingest_channel") or "#ingest"
    return OperationsSlack(channel=channel)


def customer_support_slack() -> OperationsSlack:
    channel = slack_cfg().get("customer_support_channel") or "#customer-support"
    return OperationsSlack(channel=channel)


def events_slack() -> OperationsSlack:
    channel = slack_cfg().get("events_channel") or "#events"
    return OperationsSlack(channel=channel)


def growth_slack() -> OperationsSlack:
    channel = slack_cfg().get("growth_channel") or "#growth"
    return OperationsSlack(channel=channel)


def partnership_digest_slack() -> OperationsSlack:
    user = (slack_cfg().get("partnership_digest_user") or "").strip()
    if user:
        return OperationsSlack(channel=user)
    channel = slack_cfg().get("partnership_digest_channel") or "#partnerships"
    return OperationsSlack(channel=channel)
