"""Gmail Customer Support Agent — Slack summary for Customer mail.

Dispatched by gmail_manager. Posts a concise summary (with source mailbox) to
#customer-support for each unhandled ``Customer`` routing record.

SDK: Neither (Slack SDK via operations_slack).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import mailbox_id
from company_brain.agents.operations.shared.mail_body import plain_text
from company_brain.agents.operations.shared.operations_slack import customer_support_notifier
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig
from company_brain.notify import ACTIONABLE, Signal

SPECIALIST_KEY = "customer_support"


class CustomerSupportAgent(BaseAgent):
    """Notify #customer-support about customer-tagged mail."""

    name = "customer_support"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return bool(self._store.unhandled_for(
            SPECIALIST_KEY, mailbox=self.mailbox, domain_tag="Customer",
        ))

    def run(self, **kwargs: Any) -> dict[str, Any]:
        posted = 0
        for record in self._store.unhandled_for(
            SPECIALIST_KEY, mailbox=self.mailbox, domain_tag="Customer",
        ):
            try:
                message = rest.get_message(record.message_id, mailbox=self.mailbox)
                subject = record.extracted.get("subject") or rest.message_subject_from(message)
                from_ = record.extracted.get("from") or rest.message_from(message)
                preview = plain_text(message, max_chars=400)
                text = (
                    f"*Customer mail* ({self.mailbox})\n"
                    f"*Subject:* {subject}\n"
                    f"*From:* {from_}\n\n"
                    f"{preview[:400]}"
                )
                if customer_support_notifier().emit(Signal(text=text, severity=ACTIONABLE)):
                    posted += 1
                self._store.mark_handled(record, SPECIALIST_KEY)
            except Exception:
                self.logger.exception("Customer support notify failed for %s", record.message_id)
        return {"posted": posted}
