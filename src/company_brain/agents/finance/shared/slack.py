"""Slack helper for finance agents.

Uses the Slack SDK to access the Slack API directly (per project convention —
no MCP wrapper). Posts to a configurable channel (default ``#finance``).

Requires ``SLACK_BOT_TOKEN`` in the environment. The target channel is read
from ``config/finance.yaml`` (``slack.channel`` / ``slack.channel_id``).
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class SlackNotifier:
    """Thin wrapper around slack_sdk.WebClient for finance notifications."""

    def __init__(self, channel: str, token: str | None = None):
        self.channel = channel
        self._token = token or os.getenv("SLACK_BOT_TOKEN", "")
        self._client = None

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from slack_sdk import WebClient
            except ImportError as e:
                raise RuntimeError(
                    "slack-sdk not installed. Add it to dependencies: pip install slack-sdk"
                ) from e
            if not self._token:
                raise RuntimeError("SLACK_BOT_TOKEN not set — see .env")
            self._client = WebClient(token=self._token)
        return self._client

    def post(self, text: str, blocks: list[dict] | None = None) -> str | None:
        """Post a message to the configured channel; return the message ts."""
        from slack_sdk.errors import SlackApiError

        try:
            resp = self.client.chat_postMessage(
                channel=self.channel,
                text=text,
                blocks=blocks,
            )
            logger.info("Posted to Slack %s (ts=%s)", self.channel, resp.get("ts"))
            return resp.get("ts")
        except SlackApiError as e:
            logger.error("Slack post failed: %s", e.response.get("error") if e.response else e)
            return None


def from_config(finance_config: dict[str, Any] | None) -> SlackNotifier:
    """Build a SlackNotifier from the finance config block."""
    slack_cfg = (finance_config or {}).get("slack", {}) or {}
    channel = slack_cfg.get("channel_id") or slack_cfg.get("channel") or "#finance"
    return SlackNotifier(channel=channel)
