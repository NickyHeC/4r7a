"""Investor Tracker Agent — confirmed investor interactions on contact entities.

``Investor`` (confirmed wiki index at triage) → append interaction on
``crm/contact/{slug}`` with ``segment: investor``. Cold investor interest is
handled by ``inbound_crm``.

SDK: Neither (deterministic wiki writes).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import mailbox_id
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.agents.operations.shared.wiki_crm import format_mail_section
from company_brain.config import AppConfig
from company_brain.crm.contacts import record_interaction_on_contact

SPECIALIST_KEY = "investor_tracker"
INVESTOR_TAG = "Investor"


class InvestorTrackerAgent(BaseAgent):
    """Append confirmed investor mail to CRM contact pages."""

    name = "investor_tracker"

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
                from_ = record.extracted.get("from") or rest.message_from(message)
                section = format_mail_section(record, message)
                if record_interaction_on_contact(
                    from_,
                    section,
                    segment="investor",
                ):
                    updated += 1
                self._store.mark_handled(record, SPECIALIST_KEY)
            except Exception:
                self.logger.exception("Investor tracker failed for %s", record.message_id)
        return {"updated": updated}

    def _pending(self):
        return self._store.unhandled_with_any_tag(
            SPECIALIST_KEY,
            {INVESTOR_TAG},
            mailbox=self.mailbox,
        )
