"""Slack Events API router — message and reaction dispatch."""

from __future__ import annotations

import logging
from typing import Any

from company_brain.agents.operations.slack import channels_config, slack_client
from company_brain.agents.operations.slack.ingest_triage import IngestTriageAgent
from company_brain.agents.operations.slack.open_threads import handle_reaction_added
from company_brain.agents.operations.slack.routing import SlackRoutingStore
from company_brain.config import AppConfig

logger = logging.getLogger(__name__)


class SlackEventsRouter:
    """Route Slack Events API payloads to platform specialists."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._routing = SlackRoutingStore()

    def handle_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_type = payload.get("type")
        if event_type == "url_verification":
            return {"challenge": payload.get("challenge")}

        if event_type != "event_callback":
            return {"status": "ignored", "reason": event_type or "unknown"}

        event = payload.get("event") or {}
        inner = str(event.get("type") or "")
        if inner == "message":
            return self._handle_message(event)
        if inner == "reaction_added":
            return self._handle_reaction(event)
        if inner == "member_joined_channel":
            return self._handle_member_joined(event)
        return {"status": "ignored", "reason": inner or "unknown"}

    def _handle_message(self, event: dict[str, Any]) -> dict[str, Any]:
        channel_id = str(event.get("channel") or "")
        if not channel_id:
            return {"status": "skipped", "reason": "no_channel"}

        if event.get("channel_type") == "channel" and channels_config.is_connect_channel(
            channel_id
        ):
            entry = channels_config.get_channel(channel_id) or {}
            if not entry.get("customer_support"):
                return {"status": "skipped", "reason": "connect_not_enabled"}

        agent = IngestTriageAgent(self.config)
        return agent.process_message(channel_id, event)

    def _handle_reaction(self, event: dict[str, Any]) -> dict[str, Any]:
        item = event.get("item") or {}
        if item.get("type") != "message":
            return {"status": "skipped", "reason": "not_message_reaction"}
        channel_id = str(item.get("channel") or "")
        thread_ts = str(item.get("ts") or "")
        reaction = str(event.get("reaction") or "")
        user_id = str(event.get("user") or "")
        if not channel_id or not thread_ts:
            return {"status": "skipped", "reason": "missing_target"}
        return handle_reaction_added(
            channel_id=channel_id,
            thread_ts=thread_ts,
            reaction=reaction,
            user_id=user_id,
            routing=self._routing,
        )

    def _handle_member_joined(self, event: dict[str, Any]) -> dict[str, Any]:
        channel_id = str(event.get("channel") or "")
        user = str(event.get("user") or "")
        try:
            bot_id = slack_client.bot_user_id()
        except slack_client.SlackClientError:
            bot_id = ""
        if bot_id and user == bot_id:
            channels_config.upsert_channel(channel_id, is_member=True)
            return {"status": "bot_joined", "channel_id": channel_id}
        return {"status": "ignored"}
