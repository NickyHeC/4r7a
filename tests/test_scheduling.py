"""Scheduling helper tests."""

from datetime import datetime, time

from company_brain.agents.operations.shared.scheduling import is_scheduled_moment


def test_scheduled_moment_match():
    now = datetime(2026, 6, 19, 8, 0)  # Friday
    assert is_scheduled_moment(now, "friday", time(8, 0)) is True


def test_scheduled_moment_wrong_day():
    now = datetime(2026, 6, 18, 8, 0)  # Thursday
    assert is_scheduled_moment(now, "friday", time(8, 0)) is False
