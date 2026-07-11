"""Discord Technical Absorb — batch discussion/technical threads to raw entries.

Queues community Discord conversations for the wiki absorb writer. Non-urgent
daily batch; does not invoke the LLM absorb loop itself.

SDK: Neither (deterministic extraction + raw entry writes).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.discord import channels_config, discord_client
from company_brain.agents.growth.discord import discord_config as cfg
from company_brain.agents.growth.discord.routing import DiscordRoutingRecord, DiscordRoutingStore
from company_brain.config import AppConfig, resolve_raw_dir
from company_brain.ingestion.entry import RawEntry

SPECIALIST_KEY = "technical_absorb"
ABSORB_KINDS = {
    "discussion_pending",
    "technical_pending",
    "discussion_open",
}
MIN_WORDS = 20


class TechnicalAbsorbAgent(BaseAgent):
    """Enqueue Discord technical discussions as raw wiki entries."""

    name = "discord_technical_absorb"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._routing = DiscordRoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        if not discord_client.discord_is_configured():
            return False
        now = datetime.now(timezone.utc)
        if now.hour < cfg.absorb_batch_hour_utc():
            return False
        return True

    def run(self, **kwargs: Any) -> dict[str, Any]:
        enqueued = 0
        skipped = 0
        for record in self._pending_records():
            result = self._enqueue_record(record)
            if result.get("status") == "enqueued":
                enqueued += 1
            else:
                skipped += 1
        return {"enqueued": enqueued, "skipped": skipped}

    def _pending_records(self):
        for record in self._routing.iter_all():
            if not record.community:
                continue
            if record.kind not in ABSORB_KINDS:
                continue
            if not record.handled.get("community_intake"):
                continue
            if record.handled.get(SPECIALIST_KEY) and not self._needs_refresh(record):
                continue
            parent = record.parent_channel_id or record.channel_id
            if channels_config.is_out_of_scope(parent):
                continue
            yield record

    def _enqueue_record(self, record: DiscordRoutingRecord) -> dict[str, Any]:
        parent = record.parent_channel_id or record.channel_id
        title, body = self._conversation_text(record)
        if _word_count(body) < MIN_WORDS:
            self._routing.mark_handled(record, SPECIALIST_KEY)
            record.extracted["absorb_status"] = "too_short"
            self._routing.write(record)
            return {"status": "skipped", "reason": "too_short"}

        signature = hashlib.sha256(body.encode()).hexdigest()[:16]
        if record.extracted.get("absorb_signature") == signature and record.handled.get(
            SPECIALIST_KEY
        ):
            return {"status": "skipped", "reason": "unchanged"}

        entry = RawEntry(
            source_type="discord",
            source_id=f"{parent}:{record.thread_id}",
            title=title,
            content=body,
            metadata={
                "channel_id": parent,
                "thread_id": record.thread_id,
                "permalink": (record.extracted or {}).get("permalink", ""),
                "author_handle": (record.extracted or {}).get("author_handle", ""),
                "category": (record.extracted or {}).get("category", "discussion"),
            },
            tags=["discord", "community", "technical"],
        )
        _persist_raw_entry(entry)

        record.extracted["raw_entry_id"] = entry.id
        record.extracted["absorb_signature"] = signature
        record.extracted["absorb_status"] = "queued"
        self._routing.write(record)
        self._routing.mark_handled(record, SPECIALIST_KEY)
        return {"status": "enqueued", "entry_id": entry.id}

    def _needs_refresh(self, record: DiscordRoutingRecord) -> bool:
        _, body = self._conversation_text(record)
        signature = hashlib.sha256(body.encode()).hexdigest()[:16]
        return signature != record.extracted.get("absorb_signature")

    def _conversation_text(self, record: DiscordRoutingRecord) -> tuple[str, str]:
        preview = str((record.extracted or {}).get("text_preview") or "")
        parent = record.parent_channel_id or record.channel_id
        title = str(
            (record.extracted or {}).get("title_preview") or preview[:120] or "Discord thread"
        )
        try:
            messages = discord_client.fetch_conversation_messages(parent, record.thread_id)
            if messages:
                parts = [str(m.get("content") or "") for m in messages]
                combined = "\n\n".join(p for p in parts if p.strip())
                if combined.strip():
                    first = (combined.splitlines()[0] if combined else title)[:120]
                    return first or title, combined[:12000]
        except discord_client.DiscordClientError:
            pass
        return title, preview


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


def _persist_raw_entry(entry: RawEntry) -> None:
    entries_dir = resolve_raw_dir() / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)
    path = entries_dir / entry.filename()
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(entry.to_doc().serialize())
    tmp.replace(path)
