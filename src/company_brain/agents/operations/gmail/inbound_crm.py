"""Inbound CRM Agent — typed inbound wiki pages + score-gated #growth alerts.

All CRM cold inbound tags write ``crm/inbound/{type}/`` pages (and dual-write
known contacts). Press and event invitations emit selective ``#growth`` Slack
alerts when score meets threshold.

SDK: Neither (heuristics + wiki + Slack notifier).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import mailbox_id
from company_brain.agents.operations.shared.inbound_score import score_inbound, should_slack_alert
from company_brain.agents.operations.shared.mail_body import plain_text
from company_brain.agents.operations.shared.operations_slack import channel_notifier
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig
from company_brain.crm.config import growth_channel
from company_brain.crm.inbound import INBOUND_TAGS, inbound_type_for_record, write_inbound_item
from company_brain.crm.registry import lookup_contact
from company_brain.notify import ACTIONABLE, Signal

SPECIALIST_KEY = "inbound_crm"


class InboundCrmAgent(BaseAgent):
    """Write CRM inbound pages; notify #growth for high-score press/events."""

    name = "inbound_crm"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()
        self._notifier = channel_notifier(growth_channel())

    def should_run(self, **kwargs: Any) -> bool:
        return bool(self._pending())

    def run(self, **kwargs: Any) -> dict[str, Any]:
        written = 0
        alerted = 0
        for record in self._pending():
            inbound_type = inbound_type_for_record(record)
            if not inbound_type:
                continue
            try:
                message = rest.get_message(record.message_id, mailbox=self.mailbox)
                subject = record.extracted.get("subject") or rest.message_subject_from(message)
                from_ = record.extracted.get("from") or rest.message_from(message)
                preview = plain_text(message, max_chars=2000)
                entry = lookup_contact(from_)
                scored = score_inbound(
                    inbound_type,
                    subject=subject,
                    from_hdr=from_,
                    body=preview,
                    registry_entry=entry,
                )
                notify = should_slack_alert(inbound_type, scored)
                write_inbound_item(
                    record,
                    message,
                    inbound_type=inbound_type,
                    score=scored.score,
                    score_reasons=scored.reasons,
                    slack_notified=notify,
                )
                written += 1
                if notify:
                    self._emit_slack(inbound_type, subject, from_, scored.score, preview)
                    alerted += 1
                self._store.mark_handled(record, SPECIALIST_KEY)
            except Exception:
                self.logger.exception("Inbound CRM failed for %s", record.message_id)
        return {"written": written, "slack_alerts": alerted}

    def _emit_slack(
        self,
        inbound_type: str,
        subject: str,
        from_: str,
        score: int,
        preview: str,
    ) -> None:
        label = inbound_type.replace("-", " ").title()
        text = (
            f"*{label}* (score {score})\n*Subject:* {subject}\n*From:* {from_}\n\n{preview[:400]}"
        )
        self._notifier.emit(Signal(text=text, severity=ACTIONABLE))

    def _pending(self):
        return self._store.unhandled_with_any_tag(
            SPECIALIST_KEY,
            INBOUND_TAGS,
            mailbox=self.mailbox,
        )
