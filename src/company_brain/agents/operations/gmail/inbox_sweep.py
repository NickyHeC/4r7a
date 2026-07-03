"""Inbox Sweep Agent — nightly lifecycle (archive by rules).

Ephemeral agent dispatched by gmail_manager at 22:00 workdays. Deterministic
Gmail REST only — no LLM.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import mailbox_id
from company_brain.agents.operations.shared.labels import archive
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig


class InboxSweepAgent(BaseAgent):
    """Archive messages whose lifecycle conditions are met."""

    name = "inbox_sweep"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def run(self, **kwargs: Any) -> dict[str, Any]:
        archived = 0
        for record in self._store.iter_mailbox(self.mailbox):
            if not rest.is_in_inbox(rest.get_message(record.message_id, mailbox=self.mailbox)):
                continue
            try:
                if self._should_archive(record):
                    archive(record.message_id, mailbox=self.mailbox)
                    archived += 1
            except Exception:
                self.logger.exception("Sweep failed for %s", record.message_id)
        self.logger.info("Sweep archived %d message(s)", archived)
        return {"archived": archived}

    def _should_archive(self, record) -> bool:
        msg = rest.get_message(record.message_id, mailbox=self.mailbox)
        tags = record.domain_tags
        attention = record.attention

        if attention == "2. Reply":
            thread = rest.get_thread(record.thread_id, mailbox=self.mailbox)
            return rest.thread_has_sent_reply(thread, mailbox=self.mailbox)

        if attention == "3. FYI":
            return not rest.is_unread(msg)

        if any(t.startswith("Newsletters/") for t in tags):
            return self._older_than(msg, days=1)

        if "Receipts" in tags:
            return self._older_than(msg, days=1)

        if "Meeting" in tags:
            return not rest.is_unread(msg)

        from company_brain.crm.retention import crm_inbound_archive_due

        if crm_inbound_archive_due(record):
            return True

        return False

    @staticmethod
    def _older_than(message: dict[str, Any], *, days: int) -> bool:
        internal = message.get("internalDate")
        if not internal:
            return False
        ts = datetime.fromtimestamp(int(internal) / 1000, tz=timezone.utc)
        return ts < datetime.now(timezone.utc) - timedelta(days=days)
