"""Slack Ingest Triage — tier 0/1 classification into routing records.

Hot lane: immediate routing records + optional ``action_items`` dispatch.
Cold lane: deferred informational records. Respects ``ingest_mode`` and
out-of-scope channels.

SDK: Neither (heuristics + orchestration).
"""

from __future__ import annotations

import json
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.operations.slack import channels_config, slack_client
from company_brain.agents.operations.slack.routing import SlackRoutingStore
from company_brain.agents.operations.slack.triage_heuristics import (
    TriageResult,
    classify_tier0,
    classify_tier1,
)
from company_brain.config import AppConfig

DEBOUNCE_KEY_PREFIX = "slack_triage_buffer:"


class IngestTriageAgent(BaseAgent):
    """Classify Slack messages and upsert routing records."""

    name = "ingest_triage"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._routing = SlackRoutingStore()
        self._state = StateStore()

    def should_run(self, **kwargs: Any) -> bool:
        return slack_client.slack_is_configured()

    def run(
        self,
        *,
        channel_id: str | None = None,
        message: dict[str, Any] | None = None,
        flush_channel: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if flush_channel:
            return self.flush_channel(flush_channel)

        if channel_id and message:
            return self.process_message(channel_id, message)

        return {"status": "skipped", "reason": "no_input"}

    def process_message(self, channel_id: str, message: dict[str, Any]) -> dict[str, Any]:
        bot_id = ""
        try:
            bot_id = slack_client.bot_user_id()
        except slack_client.SlackClientError:
            pass

        result = classify_tier0(message, channel_id=channel_id, bot_user_id=bot_id)
        if result.urgency == "skip":
            return {"status": "skipped", "reason": result.reason}

        if result.urgency == "immediate":
            return self._apply_immediate(channel_id, message, result)

        return self._buffer_deferred(channel_id, message)

    def flush_channel(self, channel_id: str) -> dict[str, Any]:
        raw = self._state.get(f"{DEBOUNCE_KEY_PREFIX}{channel_id}")
        if not raw:
            return {"status": "skipped", "reason": "empty_buffer"}
        try:
            messages = json.loads(raw)
        except json.JSONDecodeError:
            messages = []
        self._state.delete(f"{DEBOUNCE_KEY_PREFIX}{channel_id}")
        result = classify_tier1(messages, channel_id=channel_id)
        if result.urgency == "skip":
            return {"status": "skipped", "reason": result.reason}
        last = messages[-1] if messages else {}
        return self._apply_immediate(channel_id, last, result)

    def _buffer_deferred(self, channel_id: str, message: dict[str, Any]) -> dict[str, Any]:
        key = f"{DEBOUNCE_KEY_PREFIX}{channel_id}"
        raw = self._state.get(key)
        try:
            batch = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            batch = []
        batch.append(message)
        self._state.set(key, json.dumps(batch))
        if len(batch) >= 20:
            return self.flush_channel(channel_id)
        return {"status": "buffered", "count": len(batch)}

    def _apply_immediate(
        self,
        channel_id: str,
        message: dict[str, Any],
        result: TriageResult,
    ) -> dict[str, Any]:
        thread_ts = str(message.get("thread_ts") or message.get("ts") or "")
        message_ts = str(message.get("ts") or "")
        if not thread_ts:
            return {"status": "skipped", "reason": "no_thread_ts"}

        channel_label = slack_client.channel_label(
            channel_id,
            name=channels_config.channel_name(channel_id),
        )
        record = self._routing.upsert(
            channel_label,
            thread_ts,
            kind=result.kind,
            attention=result.attention,
            assignees=result.assignees,
            customer=result.customer,
            extracted={
                "message_ts": message_ts,
                "channel_id": channel_id,
                "text_preview": str(message.get("text") or "")[:400],
                "triage_reason": result.reason,
            },
        )
        channels_config.upsert_channel(channel_id, name=channels_config.channel_name(channel_id))

        dispatch_result: dict[str, Any] | None = None
        if result.dispatch_action_items:
            dispatch_result = self._maybe_dispatch_action_items(
                channel_label,
                thread_ts,
                message_ts,
                str(message.get("text") or ""),
                str(message.get("user") or ""),
                record,
            )

        return {
            "status": "routed",
            "kind": record.kind,
            "attention": record.attention,
            "dispatch": dispatch_result,
        }

    def _maybe_dispatch_action_items(
        self,
        channel: str,
        thread_ts: str,
        message_ts: str,
        text: str,
        slack_user_id: str,
        record: Any,
    ) -> dict[str, Any]:
        if record.handled.get("action_items"):
            return {"status": "skipped", "reason": "already_handled"}
        from company_brain.agents.operations.slack.action_items import ActionItemsAgent
        from company_brain.runtime import get_runtime

        result = get_runtime().run(
            ActionItemsAgent,
            self.config,
            channel=channel,
            thread_ts=thread_ts,
            message_ts=message_ts,
            text=text,
            slack_user_id=slack_user_id,
        )
        if result.get("status") == "created":
            self._routing.mark_handled(record, "action_items")
        return result
