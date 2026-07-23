"""Connection Agent — People / warm intro mail on CRM contact entities.

``People`` and ``Warm intro`` → ``crm/contact/{slug}`` with ``segment: connection``.
Excludes ``contact_type: investor``.

SDK: Neither (deterministic wiki writes).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import mailbox_id
from company_brain.agents.operations.shared.profiles import profile_spec
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.agents.operations.shared.wiki_crm import format_mail_section
from company_brain.config import AppConfig
from company_brain.crm.contacts import record_interaction_on_contact

SPECIALIST_KEY = "connection"


class ConnectionAgent(BaseAgent):
    """Append People / warm-intro interactions to CRM contact pages."""

    name = "connection"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return bool(self._pending())

    def run(self, **kwargs: Any) -> dict[str, Any]:
        updated = 0
        warm = 0
        for record in self._pending():
            try:
                message = rest.get_message(record.message_id, mailbox=self.mailbox)
                from_ = record.extracted.get("from") or rest.message_from(message)
                section = format_mail_section(record, message)
                if record_interaction_on_contact(
                    from_,
                    section,
                    segment="connection",
                ):
                    updated += 1
                if "Warm intro" in (record.domain_tags or []):
                    if self._notify_warm_intro(record, from_):
                        warm += 1
                self._store.mark_handled(record, SPECIALIST_KEY)
            except Exception:
                self.logger.exception("Connection CRM failed for %s", record.message_id)
        return {"updated": updated, "warm_intro_notified": warm}

    def _notify_warm_intro(self, record, from_: str) -> bool:
        from company_brain.agents.operations.shared.gmail_config import slack_cfg
        from company_brain.agents.operations.shared.operations_slack import channel_notifier
        from company_brain.notify import ACTIONABLE, Signal

        subject = (record.extracted or {}).get("subject") or ""
        text = (
            f"Warm intro from confirmed connection `{from_}` — {subject[:100]}. "
            "Optional draft only (never send)."
        )
        try:
            channel = str(slack_cfg().get("ingest_channel") or "#ingest")
            return channel_notifier(channel).emit(Signal(text=text, severity=ACTIONABLE))
        except Exception:
            self.logger.exception("Warm intro notify failed")
            return False

    def _pending(self):
        tags = {"People"}
        if profile_spec(self.mailbox).warm_intro:
            tags.add("Warm intro")
        return self._store.unhandled_with_any_tag(
            SPECIALIST_KEY,
            tags,
            mailbox=self.mailbox,
            exclude_contact_type="investor",
        )
