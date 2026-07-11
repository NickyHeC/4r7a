"""Internal Meeting Scheduler — @wiki meeting requests in internal Slack channels.

Proposes calendar slots from ``calendar_availability``; books when a time is
confirmed in-thread. Partial availability: posts whatever slots exist even when
some attendee calendars are missing (admin primary calendar is the anchor).

SDK: Neither (Calendar REST + Slack thread replies).
"""

from __future__ import annotations

import re
from typing import Any

from company_brain.agents.operations.gcal.availability import TimeSlot
from company_brain.agents.operations.gcal.book_meeting import book_meeting
from company_brain.agents.operations.gcal.calendar_availability import slots_for_scheduler
from company_brain.agents.operations.slack import slack_client

MEETING_KEYWORDS = (
    "schedule",
    "meeting",
    "find time",
    "calendar",
    "book",
    "sync",
    "call",
)

TIME_PATTERNS = (
    re.compile(
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        re.I,
    ),
    re.compile(r"\b\d{1,2}(:\d{2})?\s?(am|pm)\b", re.I),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
)


def is_meeting_request(text: str) -> bool:
    lower = (text or "").lower()
    return any(kw in lower for kw in MEETING_KEYWORDS)


def handle_internal_meeting_request(
    *,
    channel_id: str,
    thread_ts: str,
    text: str,
    slack_user_id: str,
) -> dict[str, Any]:
    """Propose slots or book when the thread confirms a time."""
    try:
        messages = slack_client.fetch_thread_replies(channel_id, thread_ts)
    except slack_client.SlackClientError as exc:
        return {"status": "error", "reason": str(exc)}

    combined = "\n".join(str(m.get("text") or "") for m in messages)
    if _has_time_confirmation(combined):
        slot = _match_slot(combined)
        if not slot:
            return _reply(channel_id, thread_ts, "I could not match a proposed slot — try again.")
        result = book_meeting(
            summary=_meeting_title(text),
            start=slot.start,
            end=slot.end,
            attendee_emails=[],
            overview=f"Scheduled via @wiki from Slack thread (requester {slack_user_id}).",
        )
        meet = result.get("meet_link") or result.get("html_link") or ""
        msg = "Booked on the primary calendar."
        if meet:
            msg += f" Meet: {meet}"
        return _reply(channel_id, thread_ts, msg)

    slots = slots_for_scheduler(importance="medium")
    if not slots:
        return _reply(
            channel_id,
            thread_ts,
            "No open slots found on the primary calendar in the next two weeks.",
        )

    body = _proposal_body(slots, partial=True)
    return _reply(channel_id, thread_ts, body)


def _proposal_body(slots: list[TimeSlot], *, partial: bool) -> str:
    lines = ["*Meeting options (primary calendar)*", ""]
    if partial:
        lines.append("_Partial view: attendee calendars without bindings are not checked._")
        lines.append("")
    for slot in slots:
        lines.append(f"• {slot.label()}")
    lines.extend(
        [
            "",
            "Reply with the option that works and I will book it.",
        ]
    )
    return "\n".join(lines)


def _has_time_confirmation(text: str) -> bool:
    lower = text.lower()
    confirm = ("works for me", "let's do", "lets do", "sounds good", "book it", "that works")
    if not any(p in lower for p in confirm):
        return False
    return any(p.search(text) for p in TIME_PATTERNS)


def _match_slot(text: str) -> TimeSlot | None:
    slots = slots_for_scheduler(importance="medium")
    lower = text.lower()
    for slot in slots:
        day = slot.start.strftime("%A").lower()
        time_label = slot.start.strftime("%I:%M %p").lstrip("0").lower()
        if day in lower and time_label in lower:
            return slot
    return slots[0] if slots else None


def _meeting_title(text: str) -> str:
    first = (text or "").strip().splitlines()[0] if text else ""
    cleaned = re.sub(r"<@[^>]+>", "", first).strip()
    return (cleaned[:80] or "Internal meeting").strip()


def _reply(channel_id: str, thread_ts: str, text: str) -> dict[str, Any]:
    try:
        ts = slack_client.post_thread_reply(channel_id, thread_ts, text)
        return {"status": "replied", "ts": ts}
    except slack_client.SlackClientError as exc:
        return {"status": "error", "reason": str(exc)}
