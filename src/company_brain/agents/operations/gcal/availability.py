"""Availability slot computation for Google Calendar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from company_brain.agents.operations.gcal import gcal_rest as rest
from company_brain.agents.operations.shared.gcal_config import (
    business_hours,
    calendar_id,
    significant_event_keywords,
    significant_event_min_minutes,
    timezone_name,
)


@dataclass(frozen=True)
class TimeSlot:
    start: datetime
    end: datetime

    def label(self) -> str:
        return (
            f"{self.start.strftime('%a %b %d, %I:%M %p')} – "
            f"{self.end.strftime('%I:%M %p')} {self.start.tzname() or ''}".strip()
        )


def find_available_slots(
    *,
    duration_minutes: int = 30,
    days_ahead: int = 14,
    slot_count: int = 3,
    importance: str = "medium",
    start_day: date | None = None,
) -> list[TimeSlot]:
    """Return open meeting slots during business hours."""
    tz = ZoneInfo(timezone_name())
    today = start_day or datetime.now(tz).date()
    bh_start, bh_end = business_hours()
    range_start = datetime.combine(today, bh_start, tzinfo=tz)
    range_end = datetime.combine(today + timedelta(days=days_ahead), bh_end, tzinfo=tz)

    busy_map = rest.free_busy(range_start, range_end, calendars=[calendar_id()])
    busy = busy_map.get(calendar_id()) or []
    busy_blocks = [_busy_block(b) for b in busy]

    significant_ends: list[datetime] = []
    if importance == "low":
        significant_ends = _significant_event_ends(range_start, range_end)

    slots: list[TimeSlot] = []
    for offset in range(days_ahead):
        day = today + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        day_start = datetime.combine(day, bh_start, tzinfo=tz)
        day_end = datetime.combine(day, bh_end, tzinfo=tz)
        cursor = day_start
        if importance == "low":
            cursor = _after_significant_events(cursor, day, significant_ends)
        while cursor + timedelta(minutes=duration_minutes) <= day_end:
            candidate_end = cursor + timedelta(minutes=duration_minutes)
            if not _overlaps_busy(cursor, candidate_end, busy_blocks):
                slots.append(TimeSlot(start=cursor, end=candidate_end))
                if len(slots) >= slot_count:
                    return slots
            cursor += timedelta(minutes=30)
    return slots


def _busy_block(raw: dict[str, str]) -> tuple[datetime, datetime]:
    return rest._parse_dt(raw["start"]), rest._parse_dt(raw["end"])


def _overlaps_busy(
    start: datetime, end: datetime, blocks: list[tuple[datetime, datetime]],
) -> bool:
    for b_start, b_end in blocks:
        if start < b_end and end > b_start:
            return True
    return False


def _significant_event_ends(range_start: datetime, range_end: datetime) -> list[datetime]:
    keywords = significant_event_keywords()
    min_minutes = significant_event_min_minutes()
    ends: list[datetime] = []
    for event in rest.list_events(range_start, range_end):
        bounds = rest.parse_event_bounds(event)
        if not bounds:
            if event.get("start", {}).get("date"):
                ends.append(range_end)
            continue
        start, end = bounds
        duration = (end - start).total_seconds() / 60
        title = (event.get("summary") or "").lower()
        if duration >= min_minutes or any(k in title for k in keywords):
            ends.append(end)
    return ends


def _after_significant_events(
    cursor: datetime, day: date, significant_ends: list[datetime],
) -> datetime:
    tz = cursor.tzinfo
    latest: datetime | None = None
    for end in significant_ends:
        if end.date() == day:
            if latest is None or end > latest:
                latest = end
    if latest and latest > cursor:
        rounded = latest.replace(second=0, microsecond=0)
        minute = (rounded.minute // 30 + 1) * 30
        hour = rounded.hour
        if minute >= 60:
            hour += 1
            minute = 0
        return datetime.combine(day, time(hour, minute), tzinfo=tz)
    return cursor
