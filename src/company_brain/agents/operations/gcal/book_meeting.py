"""Book Meeting Agent — create calendar events with guests and Meet links.

Writes to the user's Google Calendar (intentional actuation). Invites attendees,
attaches a Google Meet link when configured, and stores a short overview in the
event description.

SDK: Neither (deterministic Calendar REST).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gcal import gcal_rest as rest
from company_brain.agents.operations.shared.gcal_config import meet_conference_enabled


class BookMeetingAgent(BaseAgent):
    """Create a calendar event and invite guests."""

    name = "book_meeting"

    def run(
        self,
        *,
        summary: str,
        start: str | datetime,
        end: str | datetime,
        attendee_emails: list[str] | None = None,
        overview: str = "",
        description: str = "",
        with_meet: bool | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        start_dt = _parse(start)
        end_dt = _parse(end)
        body_desc = description or overview
        if overview and description and overview not in description:
            body_desc = f"{overview}\n\n{description}"

        event = rest.create_event(
            summary=summary,
            start=start_dt,
            end=end_dt,
            description=body_desc.strip(),
            attendee_emails=attendee_emails or [],
            with_meet=meet_conference_enabled() if with_meet is None else with_meet,
        )
        meet_link = _meet_link(event)
        return {
            "status": "ok",
            "event_id": event.get("id"),
            "html_link": event.get("htmlLink"),
            "meet_link": meet_link,
        }


def book_meeting(
    *,
    summary: str,
    start: datetime,
    end: datetime,
    attendee_emails: list[str],
    overview: str = "",
) -> dict[str, Any]:
    """Library helper for ``ext_meeting_scheduler``."""
    event = rest.create_event(
        summary=summary,
        start=start,
        end=end,
        description=overview.strip(),
        attendee_emails=attendee_emails,
        with_meet=meet_conference_enabled(),
    )
    return {
        "status": "ok",
        "event_id": event.get("id"),
        "html_link": event.get("htmlLink"),
        "meet_link": _meet_link(event),
    }


def _parse(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    cleaned = value.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned)


def _meet_link(event: dict[str, Any]) -> str | None:
    for entry in event.get("conferenceData", {}).get("entryPoints") or []:
        if entry.get("entryPointType") == "video":
            return entry.get("uri")
    return event.get("hangoutLink")
