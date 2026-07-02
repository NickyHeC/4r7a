"""Tests for work-ahead scheduling."""

from __future__ import annotations

from datetime import datetime, timezone

from company_brain.agents.scheduling.work_ahead import (
    should_run_work_ahead,
    work_ahead_run_window,
)


def test_stale_audit_runs_sunday_evening_for_monday_standup():
    # Monday 2026-06-29 09:00 UTC deadline; 15 min job + 12h buffer → Sunday ~21:00
    sunday = datetime(2026, 6, 28, 21, 30, tzinfo=timezone.utc)
    assert should_run_work_ahead(
        ready_day="monday",
        ready_time="09:00",
        estimated_minutes=15,
        buffer_minutes=720,
        now=sunday,
    )


def test_too_early_before_window():
    sunday_morning = datetime(2026, 6, 28, 8, 0, tzinfo=timezone.utc)
    assert not should_run_work_ahead(
        ready_day="monday",
        ready_time="09:00",
        estimated_minutes=15,
        buffer_minutes=720,
        now=sunday_morning,
    )


def test_run_window_end_before_deadline():
    now = datetime(2026, 6, 28, 21, 0, tzinfo=timezone.utc)
    run_at, ready_at = work_ahead_run_window(
        ready_day="monday",
        ready_time="09:00",
        estimated_minutes=15,
        buffer_minutes=720,
        now=now,
    )
    assert ready_at.weekday() == 0  # Monday
    assert run_at < ready_at
