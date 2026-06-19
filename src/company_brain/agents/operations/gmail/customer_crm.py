"""Customer CRM Agent — interaction log for active customers.

Split from gmail_customer_support: this agent writes the wiki Customer CRM
page (MD first → Notion). Only handles ``Customer``-tagged routing records.

SDK: Neither (deterministic wiki writes).
"""

from __future__ import annotations

import logging
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import customer_crm_path, mailbox_id
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.agents.operations.shared.wiki_crm import append_crm_entry, format_mail_section
from company_brain.config import AppConfig

logger = logging.getLogger(__name__)

SPECIALIST_KEY = "customer_crm"


class CustomerCRMAgent(BaseAgent):
    """Append customer interactions to the Customer CRM wiki page."""

    name = "gmail_customer_crm"
    WRITE_MODE = "append"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return bool(self._store.unhandled_for(
            SPECIALIST_KEY, mailbox=self.mailbox, domain_tag="Customer",
        ))

    def run(self, **kwargs: Any) -> dict[str, Any]:
        updated = 0
        for record in self._store.unhandled_for(
            SPECIALIST_KEY, mailbox=self.mailbox, domain_tag="Customer",
        ):
            try:
                message = rest.get_message(record.message_id, mailbox=self.mailbox)
                append_crm_entry(
                    customer_crm_path(), "Customer CRM",
                    format_mail_section(record, message),
                )
                self._store.mark_handled(record, SPECIALIST_KEY)
                updated += 1
            except Exception:
                self.logger.exception("Customer CRM update failed for %s", record.message_id)
        return {"updated": updated}
