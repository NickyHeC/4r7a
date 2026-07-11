"""Gmail Customer Mail Notify — routes Customer mail to customer_support.

Dispatched by gmail_manager. Builds a ``CustomerIntake`` for each unhandled
``Customer`` routing record and hands off to the cross-platform orchestrator
(which posts to #customer-support).

SDK: Neither (orchestration + Gmail read).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.customer_support import (
    CustomerIntake,
    CustomerSupportOrchestrator,
)
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import mailbox_id
from company_brain.agents.operations.shared.mail_body import plain_text
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig
from company_brain.crm.contacts import display_name_from_from_header, email_from_from_header

SPECIALIST_KEY = "customer_mail_notify"


class CustomerMailNotifyAgent(BaseAgent):
    """Route customer-tagged mail through the customer_support orchestrator."""

    name = "customer_mail_notify"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()
        self._orchestrator = CustomerSupportOrchestrator()

    def should_run(self, **kwargs: Any) -> bool:
        return bool(
            self._store.unhandled_for(
                SPECIALIST_KEY,
                mailbox=self.mailbox,
                domain_tag="Customer",
            )
        )

    def run(self, **kwargs: Any) -> dict[str, Any]:
        processed = 0
        for record in self._store.unhandled_for(
            SPECIALIST_KEY,
            mailbox=self.mailbox,
            domain_tag="Customer",
        ):
            try:
                message = rest.get_message(record.message_id, mailbox=self.mailbox)
                subject = record.extracted.get("subject") or rest.message_subject_from(message)
                from_ = record.extracted.get("from") or rest.message_from(message)
                preview = plain_text(message, max_chars=2000)
                email = email_from_from_header(from_)
                intake = CustomerIntake(
                    source="gmail",
                    title=subject or "Customer mail",
                    body=preview,
                    requester_email=email,
                    requester_name=display_name_from_from_header(from_),
                    mailbox=self.mailbox,
                    extra={"message_id": record.message_id, "thread_id": record.thread_id},
                )
                self._orchestrator.process(intake)
                processed += 1
                self._store.mark_handled(record, SPECIALIST_KEY)
            except Exception:
                self.logger.exception("Customer mail notify failed for %s", record.message_id)
        return {"processed": processed}
