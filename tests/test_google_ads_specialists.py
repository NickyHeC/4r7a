"""Unit tests for Google Ads specialist Markdown renderers and pacing alerts."""

from __future__ import annotations

from datetime import date, datetime, timezone

from company_brain.agents.growth.google_ads import google_ads_client as ads
from company_brain.agents.growth.google_ads.acquisition_cost import render_acquisition_cost
from company_brain.agents.growth.google_ads.budget_pacing import (
    campaigns_over_threshold,
    days_left_in_month,
    render_budget_pacing,
)
from company_brain.agents.growth.google_ads.campaign_status import render_campaign_status


def test_render_campaign_status_labels_types() -> None:
    rows = [
        ads.CampaignRow(
            campaign_id="1",
            name="Brand",
            status="ENABLED",
            channel_type="Search",
            start_date="2026-01-01",
            end_date="",
            budget_id="9",
            budget_name="b",
            budget_amount_micros=10_000_000,
            budget_period="DAILY",
        ),
        ads.CampaignRow(
            campaign_id="2",
            name="Scale",
            status="PAUSED",
            channel_type="Performance Max",
            start_date="2026-02-01",
            end_date="",
            budget_id="10",
            budget_name="b2",
            budget_amount_micros=50_000_000,
            budget_period="DAILY",
        ),
    ]
    body = render_campaign_status(rows, now=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc))
    assert "Brand" in body and "Search" in body
    assert "Performance Max" in body
    assert "Campaign Status" not in body  # title is frontmatter, not body H1


def test_budget_pacing_math_and_front_load_note() -> None:
    rows = [
        ads.BudgetPacingRow(
            campaign_id="1",
            name="Brand",
            status="ENABLED",
            channel_type="Search",
            budget_amount_micros=10_000_000,
            budget_period="DAILY",
            spend_micros=279_000_000,
            period_budget=310.0,
            spend=279.0,
            percent_used=90.0,
        )
    ]
    as_of = date(2026, 1, 15)
    assert days_left_in_month(as_of) == 16
    body = render_budget_pacing(rows, as_of=as_of)
    assert "front-load" in body.lower()
    assert "90.0%" in body
    assert "$279.00" in body

    alerts = campaigns_over_threshold(rows, as_of=as_of, threshold=0.9)
    assert len(alerts) == 1
    assert alerts[0]["name"] == "Brand"

    # No alert on last day of month (no days left)
    assert campaigns_over_threshold(rows, as_of=date(2026, 1, 31), threshold=0.9) == []


def test_acquisition_cost_unavailable_note() -> None:
    mtd = [
        ads.AcquisitionCostRow(
            campaign_id="1",
            name="Brand",
            channel_type="Search",
            cost_micros=100_000_000,
            conversions=0.0,
            clicks=10,
            impressions=100,
            cpa=None,
        )
    ]
    body = render_acquisition_cost(mtd=mtd, last_30=[])
    assert "CPA unavailable" in body
    assert "unavailable" in body
    assert "$100.00" in body


def test_acquisition_cost_with_cpa() -> None:
    mtd = [
        ads.AcquisitionCostRow(
            campaign_id="1",
            name="Brand",
            channel_type="Search",
            cost_micros=200_000_000,
            conversions=4.0,
            clicks=40,
            impressions=400,
            cpa=50.0,
        )
    ]
    last = [
        ads.AcquisitionCostRow(
            campaign_id="1",
            name="Brand",
            channel_type="Search",
            cost_micros=300_000_000,
            conversions=5.0,
            clicks=50,
            impressions=500,
            cpa=60.0,
        )
    ]
    body = render_acquisition_cost(mtd=mtd, last_30=last)
    assert "Month to date" in body
    assert "Last 30 days" in body
    assert "$50.00" in body
    assert "$60.00" in body
    assert "CPA unavailable" not in body
