"""Decision Propagate Agent — write sent decisions to the company timeline.

Dispatched by thread_watcher when a real decision (not a thanks/pass ack) is
detected in sent mail. Appends a section to the company timeline wiki page.

SDK: Neither (deterministic wiki write).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import company_timeline_path, mailbox_id
from company_brain.agents.operations.shared.mail_body import plain_text
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig
from company_brain.wiki.publish import APPEND, write_wiki_page

logger = logging.getLogger(__name__)

SPECIALIST_KEY = "decision_propagate"


class DecisionPropagateAgent(BaseAgent):
    """Append a decision entry to the company timeline wiki page."""

    name = "gmail_decision_propagate"
    WRITE_MODE = APPEND

    def __init__(
        self,
        config: AppConfig,
        mailbox: str | None = None,
        thread_id: str | None = None,
        message_id: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self.thread_id = thread_id
        self.message_id = message_id
        self._store = RoutingStore()

    def run(self, **kwargs: Any) -> dict[str, Any]:
        thread_id = self.thread_id or kwargs.get("thread_id")
        message_id = self.message_id or kwargs.get("message_id")
        if not thread_id or not message_id:
            return {"status": "missing_args"}

        records = self._store.find_by_thread(self.mailbox, thread_id)
        if records and SPECIALIST_KEY in records[0].handled:
            return {"status": "already_handled"}

        message = rest.get_message(message_id, mailbox=self.mailbox)
        subject = rest.message_subject_from(message)
        body = plain_text(message, max_chars=3000)
        when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        section = (
            f"## Decision — {when}\n\n"
            f"**Subject:** {subject}\n\n"
            f"**Thread:** `{thread_id}`\n\n"
            f"{body.strip()}\n"
        )
        rel_path = company_timeline_path()
        write_wiki_page(
            rel_path,
            "Company Timeline",
            section,
            mode=APPEND,
            section="operations/gmail",
        )

        for rec in records:
            self._store.mark_handled(rec, SPECIALIST_KEY)

        return {"status": "written", "path": rel_path, "thread_id": thread_id}
