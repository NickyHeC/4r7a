"""Discord Community Intake — routing records → customer_support community mode.

Scans Discord routing records and dispatches the cross-platform
``customer_support`` orchestrator in community mode (no CRM).

SDK: Neither (Discord read + orchestration).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.discord import channels_config, discord_client
from company_brain.agents.growth.discord.routing import DiscordRoutingRecord, DiscordRoutingStore
from company_brain.agents.operations.customer_support import (
    CommunityIntake,
    CustomerSupportOrchestrator,
)
from company_brain.config import AppConfig

SPECIALIST_KEY = "community_intake"
PENDING_KINDS = {
    "bug_pending",
    "feature_pending",
    "discussion_pending",
    "technical_pending",
}


class CommunityIntakeAgent(BaseAgent):
    """Process Discord conversations through community customer_support routing."""

    name = "discord_community_intake"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._routing = DiscordRoutingStore()
        self._orchestrator = CustomerSupportOrchestrator()

    def should_run(self, **kwargs: Any) -> bool:
        return discord_client.discord_is_configured()

    def run(
        self,
        *,
        channel_id: str | None = None,
        thread_id: str | None = None,
        record: DiscordRoutingRecord | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if record is not None:
            return self._handle_record(record)

        if channel_id and thread_id:
            existing = self._routing.read(channel_id, thread_id)
            if existing:
                return self._handle_record(existing)
            return {"status": "skipped", "reason": "no_record"}

        processed = 0
        for rec in self._iter_pending():
            try:
                out = self._handle_record(rec)
                if out.get("status") == "processed":
                    processed += 1
            except Exception:
                self.logger.exception(
                    "Community intake failed for %s:%s", rec.channel_id, rec.thread_id
                )
        return {"processed": processed}

    def _iter_pending(self):
        for rec in self._routing.iter_open():
            if not rec.community:
                continue
            if rec.kind not in PENDING_KINDS:
                continue
            if rec.handled.get(SPECIALIST_KEY):
                continue
            channel = rec.parent_channel_id or rec.channel_id
            if channels_config.is_out_of_scope(channel):
                continue
            yield rec

    def _handle_record(self, record: DiscordRoutingRecord) -> dict[str, Any]:
        if record.handled.get(SPECIALIST_KEY):
            return {"status": "skipped", "reason": "already_handled"}

        parent = record.parent_channel_id or record.channel_id
        if channels_config.is_out_of_scope(parent):
            return {"status": "skipped", "reason": "channel_excluded"}

        text, handle, author_id = self._conversation_text(record)
        title = str((record.extracted or {}).get("title_preview") or _title_from_text(text))
        permalink = str((record.extracted or {}).get("permalink") or "")
        category = str((record.extracted or {}).get("category") or "")

        intake = CommunityIntake(
            source="discord",
            title=title,
            body=text,
            requester_handle=handle or str((record.extracted or {}).get("author_handle") or ""),
            requester_id=author_id or str((record.extracted or {}).get("author_id") or ""),
            permalink=permalink,
            channel_id=str((record.extracted or {}).get("channel_id") or parent),
            thread_id=record.thread_id,
            message_id=str((record.extracted or {}).get("message_id") or ""),
            parent_channel_id=parent,
            category=category,
        )
        result = self._orchestrator.process_community(intake)
        self._routing.mark_handled(record, SPECIALIST_KEY)
        return {"status": "processed", **result}

    def _conversation_text(self, record: DiscordRoutingRecord) -> tuple[str, str, str]:
        preview = str((record.extracted or {}).get("text_preview") or "")
        parent = record.parent_channel_id or record.channel_id
        handle = str((record.extracted or {}).get("author_handle") or "")
        author_id = str((record.extracted or {}).get("author_id") or "")
        try:
            messages = discord_client.fetch_conversation_messages(parent, record.thread_id)
            if messages:
                root = messages[0]
                author = root.get("author") or {}
                handle = str(author.get("username") or handle)
                author_id = str(author.get("id") or author_id)
                parts = [str(m.get("content") or "") for m in messages[:8]]
                combined = "\n".join(p for p in parts if p.strip())
                if combined.strip():
                    return combined[:4000], handle, author_id
        except discord_client.DiscordClientError:
            pass
        return preview, handle, author_id


def _title_from_text(text: str) -> str:
    line = (text or "").strip().splitlines()[0] if text else ""
    return (line[:120] or "Discord message").strip()


def maybe_dispatch_community_intake(
    config: AppConfig,
    *,
    channel_id: str,
    thread_id: str,
    record: DiscordRoutingRecord,
) -> dict[str, Any] | None:
    """Hot-lane dispatch from ingest triage for immediate community records."""
    if not record.community or record.kind not in PENDING_KINDS:
        return None
    if record.handled.get(SPECIALIST_KEY):
        return None
    from company_brain.runtime import get_runtime

    return get_runtime().run(
        CommunityIntakeAgent,
        config,
        channel_id=channel_id,
        thread_id=thread_id,
        record=record,
    )
