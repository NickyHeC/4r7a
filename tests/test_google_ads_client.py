"""Unit tests for Google Ads read-only client helpers (mocked GAQL)."""

from __future__ import annotations

from datetime import date

import pytest

from company_brain.agents.growth.google_ads import google_ads_client as client


def test_google_ads_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in client._ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    assert client.google_ads_is_configured() is False
    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "dev")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_SECRET", "sec")
    monkeypatch.setenv("GOOGLE_ADS_REFRESH_TOKEN", "ref")
    monkeypatch.setenv("GOOGLE_ADS_CUSTOMER_ID", "123-456-7890")
    assert client.google_ads_is_configured() is True
    assert client.customer_id() == "1234567890"


def test_channel_type_label() -> None:
    assert client.channel_type_label("SEARCH") == "Search"
    assert client.channel_type_label("PERFORMANCE_MAX") == "Performance Max"
    assert client.channel_type_label("AdvertisingChannelType.SEARCH") == "Search"


def test_period_budget_daily_scales_by_month_days() -> None:
    # $10/day in January → $310
    budget = client.period_budget_for_month(
        amount_micros=10_000_000,
        budget_period="DAILY",
        year=2026,
        month=1,
    )
    assert budget == pytest.approx(310.0)


def test_period_budget_custom_uses_amount() -> None:
    budget = client.period_budget_for_month(
        amount_micros=500_000_000,
        budget_period="CUSTOM_PERIOD",
        year=2026,
        month=1,
    )
    assert budget == pytest.approx(500.0)


def test_pacing_percent() -> None:
    assert client.pacing_percent(90.0, 100.0) == pytest.approx(90.0)
    assert client.pacing_percent(10.0, 0.0) is None


def test_list_campaigns_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        client,
        "search",
        lambda query, **kwargs: [
            {
                "campaign": {
                    "id": "1",
                    "name": "Brand Search",
                    "status": "ENABLED",
                    "advertising_channel_type": "SEARCH",
                    "start_date": "2026-01-01",
                    "end_date": "",
                },
                "campaign_budget": {
                    "id": "9",
                    "name": "Brand budget",
                    "amount_micros": 20_000_000,
                    "period": "DAILY",
                },
            }
        ],
    )
    rows = client.list_campaigns()
    assert len(rows) == 1
    assert rows[0].name == "Brand Search"
    assert rows[0].channel_type == "Search"
    assert rows[0].budget_amount_micros == 20_000_000


def test_list_budget_pacing_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        client,
        "search",
        lambda query, **kwargs: [
            {
                "campaign": {
                    "id": "1",
                    "name": "Brand Search",
                    "status": "ENABLED",
                    "advertising_channel_type": "SEARCH",
                },
                "campaign_budget": {
                    "amount_micros": 10_000_000,
                    "period": "DAILY",
                },
                "metrics": {"cost_micros": 155_000_000},
            }
        ],
    )
    rows = client.list_budget_pacing(as_of=date(2026, 1, 15))
    assert len(rows) == 1
    assert rows[0].spend == pytest.approx(155.0)
    assert rows[0].period_budget == pytest.approx(310.0)
    assert rows[0].percent_used == pytest.approx(50.0)


def test_list_acquisition_cost_cpa_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        client,
        "search",
        lambda query, **kwargs: [
            {
                "campaign": {
                    "id": "2",
                    "name": "PMax",
                    "advertising_channel_type": "PERFORMANCE_MAX",
                },
                "metrics": {
                    "cost_micros": 100_000_000,
                    "conversions": 0,
                    "clicks": 40,
                    "impressions": 1000,
                },
            }
        ],
    )
    rows = client.list_acquisition_cost(during="THIS_MONTH")
    assert len(rows) == 1
    assert rows[0].channel_type == "Performance Max"
    assert rows[0].cpa is None
    assert rows[0].clicks == 40


def test_list_acquisition_cost_with_cpa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        client,
        "search",
        lambda query, **kwargs: [
            {
                "campaign": {
                    "id": "3",
                    "name": "Search",
                    "advertising_channel_type": "SEARCH",
                },
                "metrics": {
                    "cost_micros": 200_000_000,
                    "conversions": 4.0,
                    "clicks": 80,
                    "impressions": 2000,
                },
            }
        ],
    )
    rows = client.list_acquisition_cost(during="LAST_30_DAYS")
    assert rows[0].cpa == pytest.approx(50.0)
