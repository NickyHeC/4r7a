"""Calendar Availability Agent — return open slots for meeting scheduling.

Called by ``ext_meeting_scheduler`` (Gmail) to propose times in draft replies.
Importance affects slot selection: low-importance meetings avoid booking before
significant company calendar events.

SDK: Neither (deterministic Calendar REST + slot math).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gcal.availability import TimeSlot, find_available_slots
from company_brain.agents.operations.shared.gcal_config import (
    default_duration_minutes,
    proposal_slot_count,
)


class CalendarAvailabilityAgent(BaseAgent):
    """Compute available meeting slots on the user's calendar."""

    name = "calendar_availability"

    def run(
        self,
        *,
        duration_minutes: int | None = None,
        days_ahead: int = 14,
        slot_count: int | None = None,
        importance: str = "medium",
        **kwargs: Any,
    ) -> dict[str, Any]:
        duration = duration_minutes or default_duration_minutes()
        count = slot_count or proposal_slot_count()
        slots = find_available_slots(
            duration_minutes=duration,
            days_ahead=days_ahead,
            slot_count=count,
            importance=importance,
        )
        return {
            "slots": [_slot_dict(s) for s in slots],
            "importance": importance,
            "duration_minutes": duration,
        }


def slots_for_scheduler(importance: str = "medium") -> list[TimeSlot]:
    """Library helper for ``ext_meeting_scheduler``."""
    return find_available_slots(
        duration_minutes=default_duration_minutes(),
        days_ahead=14,
        slot_count=proposal_slot_count(),
        importance=importance,
    )


def _slot_dict(slot: TimeSlot) -> dict[str, str]:
    return {
        "start": slot.start.isoformat(),
        "end": slot.end.isoformat(),
        "label": slot.label(),
    }
