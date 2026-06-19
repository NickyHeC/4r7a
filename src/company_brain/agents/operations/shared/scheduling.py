"""Workday scheduling helpers for operations agents."""

from __future__ import annotations

from datetime import datetime, time, timedelta


def is_workday(dt: datetime | None = None) -> bool:
    dt = dt or datetime.now()
    return dt.weekday() < 5


def next_interval(
    now: datetime,
    interval_minutes: int,
    *,
    workdays_only: bool = True,
) -> datetime:
    """Next wall-clock boundary every ``interval_minutes`` (e.g. :00 and :30)."""
    base = now.replace(second=0, microsecond=0)
    minute = (base.minute // interval_minutes + 1) * interval_minutes
    hour = base.hour
    if minute >= 60:
        hour += minute // 60
        minute = minute % 60
    candidate = base.replace(hour=hour, minute=minute)
    if candidate <= now:
        candidate += timedelta(minutes=interval_minutes)
    if workdays_only:
        while not is_workday(candidate):
            candidate += timedelta(days=1)
            candidate = candidate.replace(hour=8, minute=0)
    return candidate


def next_daily_times(
    now: datetime,
    times: list[time],
    *,
    workdays_only: bool = True,
) -> datetime:
    """Next occurrence of any time in ``times`` today or on a future workday."""
    candidates: list[datetime] = []
    for day_offset in range(0, 8):
        day = now + timedelta(days=day_offset)
        if workdays_only and not is_workday(day):
            continue
        for t in times:
            candidate = day.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            if candidate > now:
                candidates.append(candidate)
    if not candidates:
        # fallback: tomorrow 8am
        nxt = now + timedelta(days=1)
        while workdays_only and not is_workday(nxt):
            nxt += timedelta(days=1)
        return nxt.replace(hour=8, minute=0, second=0, microsecond=0)
    return min(candidates)


_WEEKDAY = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def is_scheduled_moment(now: datetime, weekday_name: str, scheduled: time) -> bool:
    """True when ``now`` falls on ``weekday_name`` at ``scheduled`` (hour:minute)."""
    if now.weekday() != _WEEKDAY.get(weekday_name.lower(), 0):
        return False
    return now.hour == scheduled.hour and now.minute == scheduled.minute
