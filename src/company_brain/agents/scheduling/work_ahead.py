"""Work-ahead scheduling — start jobs early enough to finish before a deadline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def parse_time(value: str) -> tuple[int, int]:
    hour, minute = value.split(":")
    return int(hour), int(minute)


def next_deadline(
    *,
    day: str,
    time: str,
    now: datetime | None = None,
) -> datetime:
    """Next occurrence of ``day`` at ``time`` (UTC)."""
    now = now or datetime.now(timezone.utc)
    target_dow = WEEKDAYS[day.lower()]
    hour, minute = parse_time(time)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days_ahead = (target_dow - now.weekday()) % 7
    if days_ahead == 0 and now >= candidate:
        days_ahead = 7
    return candidate + timedelta(days=days_ahead)


def work_ahead_run_window(
    *,
    ready_day: str,
    ready_time: str,
    estimated_minutes: int,
    buffer_minutes: int = 45,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Return ``(run_at, ready_at)`` — start early enough to finish before deadline."""
    now = now or datetime.now(timezone.utc)
    ready_at = next_deadline(day=ready_day, time=ready_time, now=now)
    lead = timedelta(minutes=max(estimated_minutes, 1) + max(buffer_minutes, 0))
    run_at = ready_at - lead
    return run_at, ready_at


def should_run_work_ahead(
    *,
    ready_day: str,
    ready_time: str,
    estimated_minutes: int,
    buffer_minutes: int = 45,
    now: datetime | None = None,
) -> bool:
    """True when ``now`` is inside the work-ahead window for the next deadline."""
    now = now or datetime.now(timezone.utc)
    run_at, ready_at = work_ahead_run_window(
        ready_day=ready_day,
        ready_time=ready_time,
        estimated_minutes=estimated_minutes,
        buffer_minutes=buffer_minutes,
        now=now,
    )
    return run_at <= now < ready_at
