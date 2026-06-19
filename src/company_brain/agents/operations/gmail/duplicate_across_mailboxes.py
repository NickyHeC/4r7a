"""Duplicate Across Mailboxes Agent — dedupe routing when threads overlap.

When the same thread (or subject+from fingerprint) appears in multiple
connected mailboxes, marks secondary copies as duplicates of the primary
mailbox record so specialists do not double-act.

SDK: Neither (routing store only).
"""

from __future__ import annotations

import hashlib
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.shared.gmail_config import mailbox_id
from company_brain.agents.operations.shared.linear_config import connected_mailboxes
from company_brain.agents.operations.shared.routing import RoutingRecord, RoutingStore
from company_brain.config import AppConfig

SPECIALIST_KEY = "duplicate_across_mailboxes"


class DuplicateAcrossMailboxesAgent(BaseAgent):
    """Mark duplicate routing records across connected Gmail mailboxes."""

    name = "gmail_duplicate_across_mailboxes"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return len(connected_mailboxes()) > 1

    def run(self, **kwargs: Any) -> dict[str, Any]:
        mailboxes = connected_mailboxes()
        primary = mailboxes[0]
        by_thread: dict[str, tuple[str, str]] = {}
        by_fingerprint: dict[str, tuple[str, str]] = {}
        marked = 0

        for mb in mailboxes:
            for record in self._store.iter_mailbox(mb):
                if record.extracted.get("duplicate_of"):
                    continue
                fp = _fingerprint(record)
                thread_key = record.thread_id or ""
                canonical = None
                if thread_key and thread_key in by_thread:
                    canonical = by_thread[thread_key]
                elif fp in by_fingerprint:
                    canonical = by_fingerprint[fp]
                else:
                    if thread_key:
                        by_thread[thread_key] = (mb, record.message_id)
                    by_fingerprint[fp] = (mb, record.message_id)
                    continue

                canon_mb, canon_id = canonical
                if mb == canon_mb and record.message_id == canon_id:
                    continue
                record.extracted["duplicate_of"] = {"mailbox": canon_mb, "message_id": canon_id}
                record.extracted["duplicate_primary_mailbox"] = primary
                self._store.write(record)
                self._store.mark_handled(record, SPECIALIST_KEY)
                marked += 1

        return {"marked_duplicate": marked, "mailboxes": len(mailboxes)}


def _fingerprint(record: RoutingRecord) -> str:
    subject = (record.extracted.get("subject") or "").strip().lower()
    from_ = (record.extracted.get("from") or "").strip().lower()
    raw = f"{subject}|{from_}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
