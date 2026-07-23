"""Scheduling helper tests."""

from datetime import datetime, time

from company_brain.agents.finance.monthly_expense import MonthlyExpenseManager
from company_brain.agents.finance.quarterly_calculation import QuarterlyCalculationManager
from company_brain.agents.finance.request_manual_accounting import RequestManualAccountingAgent
from company_brain.agents.operations.shared.scheduling import is_scheduled_moment
from company_brain.agents.scheduling.calendar import next_calendar_run, next_daily_run, parse_hhmm


def test_scheduled_moment_match():
    now = datetime(2026, 6, 19, 8, 0)  # Friday
    assert is_scheduled_moment(now, "friday", time(8, 0)) is True


def test_scheduled_moment_wrong_day():
    now = datetime(2026, 6, 18, 8, 0)  # Thursday
    assert is_scheduled_moment(now, "friday", time(8, 0)) is False


def test_next_daily_run_rolls_after_target():
    assert next_daily_run(
        datetime(2026, 6, 18, 8, 0),
        at=time(8, 0),
    ) == datetime(2026, 6, 19, 8, 0)


def test_next_calendar_run_monthly_and_clamps_day():
    assert next_calendar_run(
        datetime(2026, 1, 31, 12, 0),
        day=31,
        at=time(9, 0),
    ) == datetime(2026, 2, 28, 9, 0)


def test_next_calendar_run_allowed_months():
    assert next_calendar_run(
        datetime(2026, 4, 5, 10, 0),
        day=5,
        at=time(10, 0),
        months={1, 4, 7, 10},
    ) == datetime(2026, 7, 5, 10, 0)


def test_parse_hhmm():
    assert parse_hhmm("07:45") == time(7, 45)


def test_finance_managers_use_configured_schedules(monkeypatch):
    config = {
        "schedules": {
            "monthly_expense": {"day_of_month": 3, "time": "07:30"},
            "quarterly_calculation": {"day_of_quarter": 7, "time": "11:15"},
            "request_manual_accounting": {"check_time": "13:20"},
        }
    }
    monkeypatch.setattr(
        "company_brain.agents.finance.monthly_expense.load_finance_config",
        lambda: config,
    )
    monkeypatch.setattr(
        "company_brain.agents.finance.quarterly_calculation.load_finance_config",
        lambda: config,
    )
    monkeypatch.setattr(
        "company_brain.agents.finance.request_manual_accounting.load_finance_config",
        lambda: config,
    )

    now = datetime(2026, 4, 1, 8, 0)
    assert MonthlyExpenseManager._next_run_time(now) == datetime(2026, 4, 3, 7, 30)
    assert QuarterlyCalculationManager._next_run_time(now) == datetime(2026, 4, 7, 11, 15)
    assert RequestManualAccountingAgent._seconds_until_check(datetime(2026, 4, 1, 12, 20)) == 3600
