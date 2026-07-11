"""Discord Ingest Triage — tier 0/1 classification into routing records.

Hot lane: immediate routing records from Gateway events.
Cold lane: deferred informational records (debounced). Respects exclude list and
channel ingest mode.

SDK: Neither (heuristics + orchestration).
"""

from __future__ import annotations

import json
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.growth.discord import channels_config, discord_client
from company_brain.agents.growth.discord import discord_config as cfg
from company_brain.agents.growth.discord.routing import DiscordRoutingStore
from company_brain.agents.growth.discord.triage_heuristics import (
    TriageResult,
    author_handle,
    author_id,
    classify_tier0,
    classify_tier1,
    message_content,
)
from company_brain.config import AppConfig

DEBOUNCE_KEY_PREFIX = "discord_triage_buffer:"


class IngestTriageAgent(BaseAgent):
    """Classify Discord messages and upsert routing records."""

    name = "discord_ingest_triage"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._routing = DiscordRoutingStore()
        self._state = StateStore()

    def should_run(self, **kwargs: Any) -> bool:
        return discord_client.discord_is_configured()

    def run(
        self,
        *,
        channel_id: str | None = None,
        message: dict[str, Any] | None = None,
        flush_channel: str | None = None,
        channel_type: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if flush_channel:
            return self.flush_channel(flush_channel)

        if channel_id and message:
            return self.process_message(channel_id, message, channel_type=channel_type)

        return {"status": "skipped", "reason": "no_input"}

    def process_message(
        self,
        channel_id: str,
        message: dict[str, Any],
        *,
        channel_type: int | None = None,
    ) -> dict[str, Any]:
        bot_id = ""
        try:
            bot_id = discord_client.bot_user_id()
        except discord_client.DiscordClientError:
            pass

        result = classify_tier0(
            message,
            channel_id=channel_id,
            bot_user_id=bot_id,
            channel_type=channel_type,
        )
        if result.urgency == "skip":
            return {"status": "skipped", "reason": result.reason}

        if result.urgency == "immediate":
            return self._apply_immediate(channel_id, message, result, channel_type=channel_type)

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
        *,
        channel_type: int | None = None,
    ) -> dict[str, Any]:
        parent_channel_id, thread_id, message_id = discord_client.conversation_ids(
            message,
            channel_type=channel_type,
            parent_id=self._parent_channel_id(channel_id, channel_type),
        )
        if not thread_id:
            return {"status": "skipped", "reason": "no_thread_id"}

        guild = cfg.guild_id() or str(message.get("guild_id") or "")
        permalink = discord_client.message_permalink(
            guild,
            str(message.get("channel_id") or channel_id),
            message_id,
        )
        text = message_content(message)
        record = self._routing.upsert(
            parent_channel_id,
            thread_id,
            parent_channel_id=parent_channel_id,
            kind=result.kind,
            attention=result.attention,
            community=True,
            extracted={
                "message_id": message_id,
                "channel_id": str(message.get("channel_id") or channel_id),
                "parent_channel_id": parent_channel_id,
                "author_id": author_id(message),
                "author_handle": author_handle(message),
                "text_preview": text[:400],
                "category": result.category,
                "triage_reason": result.reason,
                "permalink": permalink,
            },
        )
        channels_config.upsert_channel(
            parent_channel_id,
            name=channels_config.channel_name(parent_channel_id),
        )

        return {
            "status": "routed",
            "kind": record.kind,
            "attention": record.attention,
            "category": result.category,
        }

    def _parent_channel_id(self, channel_id: str, channel_type: int | None) -> str | None:
        if channel_type is None:
            meta = channels_config.get_channel(channel_id) or {}
            channel_type = int(meta.get("type", 0))
        if not discord_client.is_thread_channel(channel_type):
            return None
        meta = channels_config.get_channel(channel_id) or {}
        parent = str(meta.get("parent_id") or "")
        return parent or None
