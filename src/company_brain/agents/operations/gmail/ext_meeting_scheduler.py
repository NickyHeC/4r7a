"""External Meeting Scheduler — Gmail threads → Calendar drafts and bookings.

Lives under Gmail (reads mail, writes Calendar + Gmail drafts) but orchestrates
``calendar_availability`` and ``book_meeting`` in ``operations/gcal/``.

Flow:
1. User replied on a ``Meeting Request`` thread confirming interest → propose times
   (Gmail draft with slots from ``calendar_availability``).
2. Guest confirmed a specific time in the thread → ``book_meeting`` creates the
   event and invites the guest.

SDK: Neither (deterministic heuristics + REST).
"""

from __future__ import annotations

import re
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gcal.availability import TimeSlot
from company_brain.agents.operations.gcal.book_meeting import book_meeting
from company_brain.agents.operations.gcal.calendar_availability import slots_for_scheduler
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import mailbox_id
from company_brain.agents.operations.shared.mail_body import plain_text
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig

SPECIALIST_KEY = "ext_meeting_scheduler"

CONFIRM_PHRASES = (
    "let's meet",
    "lets meet",
    "happy to meet",
    "would love to meet",
    "sounds good",
    "works for me",
    "i'm available",
    "im available",
    "let me know what works",
    "looking forward to meeting",
)

TIME_PATTERNS = (
    re.compile(
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        re.I,
    ),
    re.compile(r"\b\d{1,2}(:\d{2})?\s?(am|pm)\b", re.I),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),
)


class ExtMeetingSchedulerAgent(BaseAgent):
    """Schedule meetings for email chains where the user agreed to meet."""

    name = "ext_meeting_scheduler"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def run(self, **kwargs: Any) -> dict[str, Any]:
        proposed = 0
        booked = 0
        skipped = 0
        for record in self._store.unhandled_for(
            SPECIALIST_KEY,
            mailbox=self.mailbox,
            domain_tag="Meeting Request",
        ):
            try:
                outcome = self._handle_record(record)
                if outcome == "proposed":
                    proposed += 1
                elif outcome == "booked":
                    booked += 1
                else:
                    skipped += 1
            except Exception:
                self.logger.exception("Meeting scheduler failed for %s", record.thread_id)
        return {"proposed": proposed, "booked": booked, "skipped": skipped}

    def _handle_record(self, record) -> str:
        thread = rest.get_thread(record.thread_id, mailbox=self.mailbox)
        sent = rest.latest_sent_message(thread, mailbox=self.mailbox)
        if not sent:
            return "skipped"

        sent_body = plain_text(sent, max_chars=4000).lower()
        if not any(p in sent_body for p in CONFIRM_PHRASES):
            return "skipped"

        guest_email = _guest_email(thread, mailbox=self.mailbox)
        importance = _meeting_importance(record)
        subject = rest.message_subject_from(thread.get("messages", [{}])[0])

        if _has_time_confirmation(thread, mailbox=self.mailbox):
            slot = _match_slot_from_thread(thread, mailbox=self.mailbox)
            if not slot:
                return "skipped"
            overview = _meeting_overview(thread, mailbox=self.mailbox)
            result = book_meeting(
                summary=subject or "Meeting",
                start=slot.start,
                end=slot.end,
                attendee_emails=[guest_email] if guest_email else [],
                overview=overview,
            )
            record.extracted["meeting_scheduler"] = {
                "status": "booked",
                "event_id": result.get("event_id"),
                "meet_link": result.get("meet_link"),
            }
            self._store.write(record)
            self._store.mark_handled(record, SPECIALIST_KEY)
            return "booked"

        slots = slots_for_scheduler(importance=importance)
        if not slots:
            return "skipped"
        body = _proposal_draft_body(slots)
        rest.create_reply_draft(record.thread_id, body, mailbox=self.mailbox)
        record.extracted["meeting_scheduler"] = {
            "status": "proposed",
            "slots": [s.label() for s in slots],
            "importance": importance,
        }
        self._store.write(record)
        self._store.mark_handled(record, SPECIALIST_KEY)
        return "proposed"


def _meeting_importance(record) -> str:
    tags = " ".join(record.domain_tags).lower()
    if "cold inbound" in tags:
        return "low"
    if record.contact_type in ("investor", "customer"):
        return "high"
    if "investor" in tags or "customer" in tags or "partnership" in tags:
        return "high"
    return "medium"


def _guest_email(thread: dict[str, Any], *, mailbox: str) -> str:
    profile = rest.get_profile(mailbox)
    me = profile.get("emailAddress", "").lower()
    for msg in reversed(thread.get("messages") or []):
        labels = msg.get("labelIds") or []
        if "SENT" in labels:
            continue
        from_hdr = rest.message_from(msg)
        match = re.search(r"<([^>]+)>", from_hdr)
        email = (match.group(1) if match else from_hdr).strip().lower()
        if email and email != me:
            return email
    return ""


def _has_time_confirmation(thread: dict[str, Any], *, mailbox: str) -> bool:
    for msg in reversed(thread.get("messages") or []):
        if "SENT" not in (msg.get("labelIds") or []):
            continue
        body = plain_text(msg, max_chars=2000)
        if any(p.search(body) for p in TIME_PATTERNS):
            return True
    return False


def _match_slot_from_thread(
    thread: dict[str, Any], *, mailbox: str,
) -> TimeSlot | None:
    slots = slots_for_scheduler(importance="medium")
    if not slots:
        return None
    for msg in reversed(thread.get("messages") or []):
        body = plain_text(msg, max_chars=2000).lower()
        for slot in slots:
            day = slot.start.strftime("%A").lower()
            time_label = slot.start.strftime("%I:%M %p").lstrip("0").lower()
            if day in body and (time_label.lower() in body or slot.start.strftime("%H:%M") in body):
                return slot
    return slots[0]


def _meeting_overview(thread: dict[str, Any], *, mailbox: str) -> str:
    inbound = (thread.get("messages") or [None])[0]
    if not inbound:
        return ""
    preview = plain_text(inbound, max_chars=400).strip()
    return f"Scheduled via company-brain meeting scheduler.\n\nThread context:\n{preview}"


def _proposal_draft_body(slots: list[TimeSlot]) -> str:
    lines = [
        "Thanks for reaching out — happy to find time.",
        "",
        "A few options that work on my end:",
    ]
    for slot in slots:
        lines.append(f"- {slot.label()}")
    lines.extend([
        "",
        "Let me know which works best and I'll send a calendar invite.",
    ])
    return "\n".join(lines)
