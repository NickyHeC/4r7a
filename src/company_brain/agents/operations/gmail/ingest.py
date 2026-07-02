"""Gmail Ingest Agent — route clear Ingest mail into raw entries.

Dispatched by thread_watcher (sent enrichment) or gmail_manager (Ingest-tagged
routing records). Clear content becomes a raw wiki entry for absorb; ambiguous
content is flagged for ingest_queue_review.

SDK: Neither (deterministic extraction).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import mailbox_id
from company_brain.agents.operations.shared.mail_body import plain_text, word_count
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig, resolve_raw_dir
from company_brain.ingestion.entry import RawEntry

SPECIALIST_KEY = "ingest"
MIN_CLEAR_WORDS = 25


class IngestAgent(BaseAgent):
    """Persist ingest-worthy Gmail content as raw entries."""

    name = "ingest"

    def __init__(
        self,
        config: AppConfig,
        mailbox: str | None = None,
        thread_id: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self.thread_id = thread_id
        self._store = RoutingStore()

    def run(self, **kwargs: Any) -> dict[str, Any]:
        thread_id = self.thread_id or kwargs.get("thread_id")
        if thread_id:
            return self._ingest_thread(thread_id)

        records = self._store.unhandled_for(
            SPECIALIST_KEY,
            mailbox=self.mailbox,
            domain_tag="Ingest",
        )
        ingested = 0
        queued = 0
        for record in records:
            result = self._ingest_thread(record.thread_id, record=record)
            if result.get("status") == "ingested":
                ingested += 1
            elif result.get("status") == "ambiguous":
                queued += 1
        return {"ingested": ingested, "ambiguous": queued}

    def _ingest_thread(self, thread_id: str, *, record=None) -> dict[str, Any]:
        records = [record] if record else self._store.find_by_thread(self.mailbox, thread_id)
        if records and SPECIALIST_KEY in records[0].handled:
            return {"status": "already_handled", "thread_id": thread_id}

        thread = rest.get_thread(thread_id, mailbox=self.mailbox)
        sent = rest.latest_sent_message(thread, mailbox=self.mailbox)
        target = sent or (thread.get("messages") or [])[-1]
        if not target:
            return {"status": "empty", "thread_id": thread_id}

        subject = rest.message_subject_from(target)
        body = plain_text(target, max_chars=12000)
        words = word_count(body)

        if words < MIN_CLEAR_WORDS:
            return self._mark_ambiguous(records, thread_id, subject, body, reason="too_short")

        entry = RawEntry(
            source_type="gmail",
            source_id=f"{self.mailbox}:{target.get('id', thread_id)}",
            title=subject or f"Gmail thread {thread_id}",
            content=body,
            metadata={
                "mailbox": self.mailbox,
                "thread_id": thread_id,
                "message_id": target.get("id"),
            },
            tags=["gmail", "ingest"],
        )
        _persist_raw_entry(entry)

        for rec in records or self._store.find_by_thread(self.mailbox, thread_id):
            rec.extracted["ingest_status"] = "clear"
            rec.extracted["raw_entry_id"] = entry.id
            self._store.write(rec)
            self._store.mark_handled(rec, SPECIALIST_KEY)

        return {"status": "ingested", "thread_id": thread_id, "entry_id": entry.id}

    def _mark_ambiguous(
        self,
        records,
        thread_id: str,
        subject: str,
        body: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        for rec in records or self._store.find_by_thread(self.mailbox, thread_id):
            rec.extracted["ingest_status"] = "ambiguous"
            rec.extracted["ingest_reason"] = reason
            rec.extracted["ingest_subject"] = subject
            rec.extracted["ingest_preview"] = body[:500]
            self._store.write(rec)
            if SPECIALIST_KEY not in rec.handled:
                self._store.mark_handled(rec, SPECIALIST_KEY)
        return {"status": "ambiguous", "thread_id": thread_id, "reason": reason}


def _persist_raw_entry(entry: RawEntry) -> None:
    entries_dir = resolve_raw_dir() / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)
    path = entries_dir / entry.filename()
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(entry.to_doc().serialize())
    tmp.replace(path)
