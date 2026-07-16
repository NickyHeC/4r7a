"""Slack Thread Absorb — distill eligible threads into ``raw/entries`` for absorb.

Twin of Discord ``technical_absorb``: deterministic transcript + metadata only;
does not invoke the LLM absorb writer. Skips Connect/customer channels.

SDK: Neither (Slack read + raw entry writes).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.slack import channels_config, slack_client
from company_brain.agents.operations.slack import slack_config as cfg
from company_brain.agents.operations.slack.routing import SlackRoutingRecord, SlackRoutingStore
from company_brain.config import AppConfig, resolve_raw_dir
from company_brain.ingestion.entry import RawEntry

SPECIALIST_KEY = "thread_absorb"
MIN_WORDS = 20


class ThreadAbsorbAgent(BaseAgent):
    """Enqueue Slack knowledge threads as raw wiki entries."""

    name = "thread_absorb"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._routing = SlackRoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        if kwargs.get("force"):
            return slack_client.slack_is_configured()
        if not slack_client.slack_is_configured():
            return False
        now = datetime.now(timezone.utc)
        return now.hour >= cfg.thread_absorb_batch_hour_utc()

    def run(self, *, force: bool = False, **kwargs: Any) -> dict[str, Any]:
        del force  # used only in should_run via execute kwargs
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
        min_age_h = cfg.thread_absorb_min_age_hours()
        now = datetime.now(timezone.utc)
        for record in self._routing.iter_all():
            if channels_config.is_connect_channel(record.channel):
                continue
            if record.customer:
                continue
            if channels_config.is_out_of_scope(record.channel):
                continue
            if not self._is_eligible(record, now=now, min_age_h=min_age_h):
                continue
            if record.handled.get(SPECIALIST_KEY) and not self._needs_refresh(record):
                continue
            yield record

    def _is_eligible(
        self,
        record: SlackRoutingRecord,
        *,
        now: datetime,
        min_age_h: int,
    ) -> bool:
        if record.handled.get("closed"):
            return True
        updated = _parse_ts(record.updated_at) or _parse_ts(record.created_at)
        if updated is None:
            return False
        age_h = (now - updated).total_seconds() / 3600.0
        return age_h >= min_age_h

    def _enqueue_record(self, record: SlackRoutingRecord) -> dict[str, Any]:
        title, body, participants = self._conversation_text(record)
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

        header = "\n".join(
            [
                f"# Slack thread — {title}",
                "",
                f"**Channel:** `{record.channel}`",
                f"**Thread:** `{record.thread_ts}`",
                f"**Kind:** {record.kind or '—'}",
                f"**Participants:** {', '.join(participants) or '—'}",
                "",
                "## Transcript",
                "",
            ]
        )
        content = header + body

        entry = RawEntry(
            source_type="slack",
            source_id=f"{record.channel}:{record.thread_ts}",
            title=title[:200] or "Slack thread",
            content=content[:16000],
            metadata={
                "channel_id": record.channel,
                "thread_ts": record.thread_ts,
                "kind": record.kind or "",
                "permalink": str((record.extracted or {}).get("permalink") or ""),
                "participants": participants,
            },
            tags=["slack", "thread", "encyclopedia"],
        )
        _persist_raw_entry(entry)

        record.extracted["raw_entry_id"] = entry.id
        record.extracted["absorb_signature"] = signature
        record.extracted["absorb_status"] = "queued"
        self._routing.write(record)
        self._routing.mark_handled(record, SPECIALIST_KEY)
        return {"status": "enqueued", "entry_id": entry.id}

    def _needs_refresh(self, record: SlackRoutingRecord) -> bool:
        _title, body, _p = self._conversation_text(record)
        signature = hashlib.sha256(body.encode()).hexdigest()[:16]
        return signature != record.extracted.get("absorb_signature")

    def _conversation_text(self, record: SlackRoutingRecord) -> tuple[str, str, list[str]]:
        preview = str((record.extracted or {}).get("text_preview") or "")
        title = str(
            (record.extracted or {}).get("title_preview") or preview[:120] or "Slack thread"
        )
        participants: list[str] = []
        try:
            messages = slack_client.fetch_thread_replies(record.channel, record.thread_ts)
            if messages:
                parts: list[str] = []
                seen: set[str] = set()
                for msg in messages:
                    user = str(msg.get("user") or msg.get("username") or "")
                    if user and user not in seen:
                        seen.add(user)
                        participants.append(user)
                    text = str(msg.get("text") or "").strip()
                    if text:
                        parts.append(f"**{user or 'unknown'}:** {text}")
                combined = "\n\n".join(parts)
                if combined.strip():
                    first_line = combined.splitlines()[0][:120]
                    return first_line or title, combined[:14000], participants
        except Exception:
            self.logger.debug("thread fetch failed for %s/%s", record.channel, record.thread_ts)
        return title, preview, participants


def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


def _persist_raw_entry(entry: RawEntry) -> None:
    entries_dir = resolve_raw_dir() / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)
    path = entries_dir / entry.filename()
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(entry.to_doc().serialize())
    tmp.replace(path)
