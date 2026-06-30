"""Recruiting Inbound Agent — job seeker mail to Inbound Candidates wiki.

Handles ``Cold Inbound/Job Seekers`` even when auto-archived at triage.

SDK: Neither (deterministic wiki writes).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import inbound_candidate_path, mailbox_id
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.agents.operations.shared.wiki_crm import append_crm_entry, format_mail_section
from company_brain.config import AppConfig

SPECIALIST_KEY = "recruiting_inbound"
JOB_SEEKERS_TAG = "Cold Inbound/Job Seekers"


class RecruitingInboundAgent(BaseAgent):
    """Append job seeker inbound to Inbound Candidates wiki."""

    name = "recruiting_inbound"
    WRITE_MODE = "append"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return bool(self._store.unhandled_for(
            SPECIALIST_KEY, mailbox=self.mailbox, domain_tag=JOB_SEEKERS_TAG,
        ))

    def run(self, **kwargs: Any) -> dict[str, Any]:
        updated = 0
        for record in self._store.unhandled_for(
            SPECIALIST_KEY, mailbox=self.mailbox, domain_tag=JOB_SEEKERS_TAG,
        ):
            try:
                message = rest.get_message(record.message_id, mailbox=self.mailbox)
                append_crm_entry(
                    inbound_candidate_path(), "Inbound Candidates",
                    format_mail_section(record, message),
                )
                self._store.mark_handled(record, SPECIALIST_KEY)
                updated += 1
            except Exception:
                self.logger.exception("Recruiting inbound failed for %s", record.message_id)
        return {"updated": updated}
