"""Calendar scheduling helpers shared by persistent department managers."""

from __future__ import annotations

import calendar
from collections.abc import Collection
from datetime import datetime, time, timedelta


def parse_hhmm(value: str) -> time:
    """Parse a 24-hour ``HH:MM`` value."""
    try:
        hour, minute = (int(part) for part in value.strip().split(":", 1))
        return time(hour, minute)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid HH:MM time: {value!r}") from exc


def next_daily_run(now: datetime, *, at: time) -> datetime:
    """Return the next daily occurrence of ``at``, preserving ``now`` timezone."""
    candidate = now.replace(
        hour=at.hour,
        minute=at.minute,
        second=0,
        microsecond=0,
    )
    return candidate if candidate > now else candidate + timedelta(days=1)


def calendar_run_for_month(
    reference: datetime,
    *,
    day: int,
    at: time,
    year: int | None = None,
    month: int | None = None,
) -> datetime:
    """Return one month's scheduled occurrence, preserving the reference timezone."""
    target_year = year or reference.year
    target_month = month or reference.month
    if target_month < 1 or target_month > 12:
        raise ValueError("month must be from 1 through 12")
    if day < 1:
        raise ValueError("day must be positive")
    candidate_day = min(day, calendar.monthrange(target_year, target_month)[1])
    return reference.replace(
        year=target_year,
        month=target_month,
        day=candidate_day,
        hour=at.hour,
        minute=at.minute,
        second=0,
        microsecond=0,
    )


def next_calendar_run(
    now: datetime,
    *,
    day: int,
    at: time,
    months: Collection[int] | None = None,
) -> datetime:
    """Return the next day/time in an allowed month.

    ``months=None`` means every month. Days beyond a month's length clamp to
    that month's final day. The returned datetime preserves ``now`` timezone.
    """
    allowed = set(months or range(1, 13))
    if not allowed or any(month < 1 or month > 12 for month in allowed):
        raise ValueError("months must contain values from 1 through 12")
    if day < 1:
        raise ValueError("day must be positive")

    for offset in range(0, 25):
        month_index = now.month - 1 + offset
        year = now.year + month_index // 12
        month = month_index % 12 + 1
        if month not in allowed:
            continue
        candidate_day = min(day, calendar.monthrange(year, month)[1])
        candidate = now.replace(
            year=year,
            month=month,
            day=candidate_day,
            hour=at.hour,
            minute=at.minute,
            second=0,
            microsecond=0,
        )
        if candidate > now:
            return candidate
    raise RuntimeError("could not resolve next calendar run within two years")
