"""Slack Events API router — message, reaction, and app_mention dispatch."""

from __future__ import annotations

import logging
import re
from typing import Any

from company_brain.agents.operations.slack import channels_config, slack_client
from company_brain.agents.operations.slack.ingest_triage import IngestTriageAgent
from company_brain.agents.operations.slack.internal_meeting_scheduler import (
    handle_internal_meeting_request,
    is_meeting_request,
)
from company_brain.agents.operations.slack.open_threads import handle_reaction_added
from company_brain.agents.operations.slack.routing import SlackRoutingStore
from company_brain.agents.operations.slack.wiki_commands import handle_wiki_command
from company_brain.config import AppConfig

logger = logging.getLogger(__name__)

MENTION_BODY_RE = re.compile(r"<@[^>]+>\s*(.*)", re.S)


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
        if inner == "app_mention":
            return self._handle_app_mention(event)
        if inner == "user_change":
            return self._handle_user_change(event)
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

    def _handle_app_mention(self, event: dict[str, Any]) -> dict[str, Any]:
        channel_id = str(event.get("channel") or "")
        thread_ts = str(event.get("thread_ts") or event.get("ts") or "")
        user_id = str(event.get("user") or "")
        text = str(event.get("text") or "")
        if not channel_id or not thread_ts:
            return {"status": "skipped", "reason": "missing_target"}

        match = MENTION_BODY_RE.match(text.strip())
        query = (match.group(1) if match else text).strip()
        first_token = (query.split(None, 1)[0] if query else "").lower()

        from company_brain.agents.operations.slack.wiki_commands import COMMAND_PREFIXES

        if first_token in COMMAND_PREFIXES:
            cmd_result = handle_wiki_command(
                channel_id=channel_id,
                thread_ts=thread_ts,
                command=first_token,
                slack_user_id=user_id,
                text=query,
            )
        else:
            cmd_result = {"status": "not_command"}
        if cmd_result.get("status") != "not_command":
            return {"status": "wiki_command", "result": cmd_result}

        if is_meeting_request(query):
            meeting = handle_internal_meeting_request(
                channel_id=channel_id,
                thread_ts=thread_ts,
                text=query,
                slack_user_id=user_id,
            )
            return {"status": "meeting_scheduler", "result": meeting}

        from company_brain.agents.operations.slack.ask_wiki import AskWikiAgent
        from company_brain.runtime import get_runtime

        result = get_runtime().run(
            AskWikiAgent,
            self.config,
            channel_id=channel_id,
            thread_ts=thread_ts,
            query=query,
            slack_user_id=user_id,
        )
        return {"status": "ask_wiki", "result": result}

    def _handle_user_change(self, event: dict[str, Any]) -> dict[str, Any]:
        from company_brain.agents.operations.slack.offboard_signal import handle_user_change_event

        return handle_user_change_event(event, self.config)

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
