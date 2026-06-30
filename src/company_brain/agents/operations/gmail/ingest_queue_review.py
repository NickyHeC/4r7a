"""Ingest Queue Review Agent — ambiguous ingest items + weekly Slack ping.

Runs from gmail_manager on the configured review day (default Monday 8am) or on
demand. Appends ambiguous ingest items to the Ingest Queue wiki page and pings
#ingest with the Notion/wiki link when Slack is configured.

SDK: Neither (deterministic wiki + Slack).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.shared.gmail_config import ingest_queue_path, mailbox_id
from company_brain.agents.operations.shared.operations_slack import ingest_notifier
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import APPEND, write_wiki_page

SPECIALIST_KEY = "ingest_queue_review"


class IngestQueueReviewAgent(BaseAgent):
    """Maintain the ingest queue page and weekly Slack reminder."""

    name = "ingest_queue_review"
    WRITE_MODE = APPEND

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def run(self, *, ping_slack: bool = True, **kwargs: Any) -> dict[str, Any]:
        ambiguous = [
            r for r in self._store.iter_mailbox(self.mailbox)
            if r.extracted.get("ingest_status") == "ambiguous"
            and SPECIALIST_KEY not in r.handled
        ]
        if not ambiguous:
            return {"queued": 0, "pinged": False}

        when = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        blocks = [f"## Ingest queue — {when}\n"]
        for rec in ambiguous:
            subject = rec.extracted.get("ingest_subject") or rec.message_id
            preview = (rec.extracted.get("ingest_preview") or "").strip()
            reason = rec.extracted.get("ingest_reason") or "ambiguous"
            blocks.append(
                f"### {subject}\n\n"
                f"- **Thread:** `{rec.thread_id}`\n"
                f"- **Reason:** {reason}\n\n"
                f"{preview}\n"
            )
            self._store.mark_handled(rec, SPECIALIST_KEY)

        rel_path = ingest_queue_path()
        write_wiki_page(
            rel_path, "Ingest Queue", "\n".join(blocks), mode=APPEND, section="operations/gmail"
        )

        pinged = False
        if ping_slack:
            pinged = self._ping_ingest_channel(len(ambiguous), rel_path)

        return {"queued": len(ambiguous), "path": rel_path, "pinged": pinged}

    def _ping_ingest_channel(self, count: int, rel_path: str) -> bool:
        try:
            return ingest_notifier().emit(Signal(
                text=f"{count} ambiguous Gmail ingest item(s) need review — see wiki `{rel_path}`.",
                severity=ACTIONABLE,
            ))
        except Exception:
            self.logger.exception("Ingest queue Slack ping failed")
            return False
