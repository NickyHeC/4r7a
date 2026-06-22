"""Growth Inbound Agent — press/podcast wiki + event Slack routing.

``Cold Inbound/Press & Podcast`` → Media Promotion wiki page.
``Cold Inbound/Event Invitations`` → #events (attend) or #growth (sponsor/co-host).

SDK: Neither (wiki + Slack).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import mailbox_id, media_promotion_path
from company_brain.agents.operations.shared.mail_body import plain_text
from company_brain.agents.operations.shared.operations_slack import events_notifier, growth_notifier
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.agents.operations.shared.wiki_crm import append_crm_entry, format_mail_section
from company_brain.config import AppConfig
from company_brain.notify import ACTIONABLE, Signal

SPECIALIST_KEY = "growth_inbound"
PRESS_TAG = "Cold Inbound/Press & Podcast"
EVENT_TAG = "Cold Inbound/Event Invitations"
SPONSOR_HINTS = ("sponsor", "co-host", "cohost", "booth", "exhibit", "partnership booth")


class GrowthInboundAgent(BaseAgent):
    """Route growth-related cold inbound to wiki and Slack."""

    name = "gmail_growth_inbound"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return bool(self._pending())

    def run(self, **kwargs: Any) -> dict[str, Any]:
        media = 0
        events = 0
        for record in self._pending():
            try:
                message = rest.get_message(record.message_id, mailbox=self.mailbox)
                if PRESS_TAG in record.domain_tags:
                    append_crm_entry(
                        media_promotion_path(), "Media Promotion",
                        format_mail_section(record, message),
                    )
                    media += 1
                elif EVENT_TAG in record.domain_tags:
                    self._notify_event(record, message)
                    events += 1
                self._store.mark_handled(record, SPECIALIST_KEY)
            except Exception:
                self.logger.exception("Growth inbound failed for %s", record.message_id)
        return {"media_updates": media, "event_notifications": events}

    def _notify_event(self, record, message) -> None:
        subject = record.extracted.get("subject") or rest.message_subject_from(message)
        from_ = record.extracted.get("from") or rest.message_from(message)
        preview = plain_text(message, max_chars=300)
        blob = f"{subject} {preview}".lower()
        sponsor = any(h in blob for h in SPONSOR_HINTS)
        notifier = growth_notifier() if sponsor else events_notifier()
        label = "sponsor/co-host" if sponsor else "attend"
        text = (
            f"*Event invitation* ({label})\n"
            f"*Subject:* {subject}\n"
            f"*From:* {from_}\n\n"
            f"{preview[:300]}"
        )
        notifier.emit(Signal(text=text, severity=ACTIONABLE))

    def _pending(self):
        return self._store.unhandled_with_any_tag(
            SPECIALIST_KEY, {PRESS_TAG, EVENT_TAG}, mailbox=self.mailbox,
        )
