"""Unit tests for PostHog manager schedule helpers."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from company_brain.agents.product.posthog_manager import iso_week_key, next_run_at


def test_iso_week_key() -> None:
    when = datetime(2026, 7, 20, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert iso_week_key(when) == "2026-W30"


def test_next_run_at_same_day_before_hour(monkeypatch) -> None:
    from company_brain.agents.product.posthog import posthog_config as cfg

    monkeypatch.setattr(cfg, "run_weekday", lambda: 0)
    monkeypatch.setattr(cfg, "run_hour", lambda: 9)
    monkeypatch.setattr(cfg, "run_minute", lambda: 0)
    now = datetime(2026, 7, 20, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    nxt = next_run_at(now)
    assert nxt == datetime(2026, 7, 20, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))


def test_next_run_at_same_day_after_hour_rolls_week(monkeypatch) -> None:
    from company_brain.agents.product.posthog import posthog_config as cfg

    monkeypatch.setattr(cfg, "run_weekday", lambda: 0)
    monkeypatch.setattr(cfg, "run_hour", lambda: 9)
    monkeypatch.setattr(cfg, "run_minute", lambda: 0)
    now = datetime(2026, 7, 20, 10, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    nxt = next_run_at(now)
    assert nxt == datetime(2026, 7, 27, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))


def test_next_run_at_midweek(monkeypatch) -> None:
    from company_brain.agents.product.posthog import posthog_config as cfg

    monkeypatch.setattr(cfg, "run_weekday", lambda: 0)
    monkeypatch.setattr(cfg, "run_hour", lambda: 9)
    monkeypatch.setattr(cfg, "run_minute", lambda: 0)
    now = datetime(2026, 7, 22, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    nxt = next_run_at(now)
    assert nxt == datetime(2026, 7, 27, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
