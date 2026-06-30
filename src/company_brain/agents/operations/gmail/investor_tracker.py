"""Investor Tracker Agent — Investors + Investor Interest.

``Investor`` (confirmed wiki list at triage) → append interaction to Investors
CRM. ``Cold Inbound/Investor Interest`` → append to Investor Interest page.

SDK: Neither (deterministic wiki writes).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import (
    investor_interest_path,
    investor_path,
    mailbox_id,
)
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.agents.operations.shared.wiki_crm import append_crm_entry, format_mail_section
from company_brain.config import AppConfig

SPECIALIST_KEY = "investor_tracker"
INVESTOR_INTEREST_TAG = "Cold Inbound/Investor Interest"


class InvestorTrackerAgent(BaseAgent):
    """Update investor CRM pages from routing records."""

    name = "investor_tracker"
    WRITE_MODE = "append"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return bool(self._pending())

    def run(self, **kwargs: Any) -> dict[str, Any]:
        crm = 0
        interests = 0
        for record in self._pending():
            try:
                message = rest.get_message(record.message_id, mailbox=self.mailbox)
                section = format_mail_section(record, message)
                is_investor = (
                    "Investor" in record.domain_tags
                    and INVESTOR_INTEREST_TAG not in record.domain_tags
                )
                if is_investor:
                    append_crm_entry(investor_path(), "Investors", section)
                    crm += 1
                elif INVESTOR_INTEREST_TAG in record.domain_tags:
                    append_crm_entry(investor_interest_path(), "Investor Interest", section)
                    interests += 1
                self._store.mark_handled(record, SPECIALIST_KEY)
            except Exception:
                self.logger.exception("Investor tracker failed for %s", record.message_id)
        return {"crm_updates": crm, "interest_updates": interests}

    def _pending(self):
        tags = {"Investor", INVESTOR_INTEREST_TAG}
        return self._store.unhandled_with_any_tag(SPECIALIST_KEY, tags, mailbox=self.mailbox)
