"""Unit tests for Google Ads manager schedule helpers."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from company_brain.agents.growth.google_ads_manager import iso_week_key, next_run_at


def test_iso_week_key() -> None:
    # 2026-07-20 is a Monday, ISO week 30
    when = datetime(2026, 7, 20, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert iso_week_key(when) == "2026-W30"


def test_next_run_at_same_day_before_hour(monkeypatch) -> None:
    from company_brain.agents.growth.google_ads import google_ads_config as cfg

    monkeypatch.setattr(cfg, "run_weekday", lambda: 0)
    monkeypatch.setattr(cfg, "run_hour", lambda: 8)
    monkeypatch.setattr(cfg, "run_minute", lambda: 0)
    now = datetime(2026, 7, 20, 7, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    nxt = next_run_at(now)
    assert nxt == datetime(2026, 7, 20, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles"))


def test_next_run_at_same_day_after_hour_rolls_week(monkeypatch) -> None:
    from company_brain.agents.growth.google_ads import google_ads_config as cfg

    monkeypatch.setattr(cfg, "run_weekday", lambda: 0)
    monkeypatch.setattr(cfg, "run_hour", lambda: 8)
    monkeypatch.setattr(cfg, "run_minute", lambda: 0)
    now = datetime(2026, 7, 20, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    nxt = next_run_at(now)
    assert nxt == datetime(2026, 7, 27, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles"))


def test_next_run_at_midweek(monkeypatch) -> None:
    from company_brain.agents.growth.google_ads import google_ads_config as cfg

    monkeypatch.setattr(cfg, "run_weekday", lambda: 0)
    monkeypatch.setattr(cfg, "run_hour", lambda: 8)
    monkeypatch.setattr(cfg, "run_minute", lambda: 0)
    # Wednesday → next Monday
    now = datetime(2026, 7, 22, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    nxt = next_run_at(now)
    assert nxt == datetime(2026, 7, 27, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
