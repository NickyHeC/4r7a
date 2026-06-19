"""Gmail CRM Agent — Company Connections for People-tagged mail.

``People`` → Company Connections wiki page. Excludes ``contact_type: investor``
so investor CRM stays in investor_tracker.

SDK: Neither (deterministic wiki writes).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import company_connections_path, mailbox_id
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.agents.operations.shared.wiki_crm import append_crm_entry, format_mail_section
from company_brain.config import AppConfig

SPECIALIST_KEY = "gmail_crm"


class GmailCRMAgent(BaseAgent):
    """Append People interactions to Company Connections."""

    name = "gmail_crm"
    WRITE_MODE = "append"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return bool(self._pending())

    def run(self, **kwargs: Any) -> dict[str, Any]:
        updated = 0
        for record in self._pending():
            try:
                message = rest.get_message(record.message_id, mailbox=self.mailbox)
                append_crm_entry(
                    company_connections_path(), "Company Connections",
                    format_mail_section(record, message),
                )
                self._store.mark_handled(record, SPECIALIST_KEY)
                updated += 1
            except Exception:
                self.logger.exception("Gmail CRM failed for %s", record.message_id)
        return {"updated": updated}

    def _pending(self):
        return self._store.unhandled_with_any_tag(
            SPECIALIST_KEY, {"People", "Warm intro"},
            mailbox=self.mailbox,
            exclude_contact_type="investor",
        )
