"""Budget Pacing — MTD spend vs Google Ads period budget.

SDK: Neither (deterministic GAQL → Markdown). Read-only at the Ads source.

Google Ads may front-load spend within a period (including a large share of the
period budget on a single day) while still respecting the period cap. This page
tracks how much of the period budget is already spent — not same-day spikes alone.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.google_ads import google_ads_client as ads
from company_brain.agents.growth.google_ads import google_ads_config as cfg
from company_brain.wiki.publish import UPDATE, write_wiki_page

WIKI_PATH = "growth/google-ads/budget-pacing.md"
TITLE = "Budget Pacing"
WRITE_MODE = UPDATE


class BudgetPacingAgent(BaseAgent):
    """Overwrite the budget pacing wiki page from a live Ads snapshot."""

    name = "budget_pacing"
    WRITE_MODE = WRITE_MODE

    def should_run(self, **kwargs: Any) -> bool:
        return ads.google_ads_is_configured()

    def run(self, **kwargs: Any) -> dict[str, Any]:
        as_of = kwargs.get("as_of")
        if not isinstance(as_of, date):
            as_of = datetime.now(cfg.tz()).date()
        rows = ads.list_budget_pacing(as_of=as_of)
        body = render_budget_pacing(rows, as_of=as_of)
        write_wiki_page(
            WIKI_PATH,
            TITLE,
            body,
            mode=WRITE_MODE,
            section="growth",
            type_="report",
        )
        alerts = campaigns_over_threshold(rows, as_of=as_of)
        return {
            "wiki_path": WIKI_PATH,
            "campaigns": len(rows),
            "pacing_alerts": alerts,
        }


def days_left_in_month(as_of: date) -> int:
    last = calendar.monthrange(as_of.year, as_of.month)[1]
    return max(0, last - as_of.day)


def campaigns_over_threshold(
    rows: list[ads.BudgetPacingRow],
    *,
    as_of: date,
    threshold: float | None = None,
) -> list[dict[str, Any]]:
    """Campaigns at/above pacing threshold with days left in the month."""
    threshold = cfg.pacing_alert_threshold() if threshold is None else threshold
    left = days_left_in_month(as_of)
    if left <= 0:
        return []
    alerts: list[dict[str, Any]] = []
    for row in rows:
        if row.percent_used is None:
            continue
        if row.percent_used / 100.0 >= threshold:
            alerts.append(
                {
                    "campaign_id": row.campaign_id,
                    "name": row.name,
                    "percent_used": row.percent_used,
                    "spend": row.spend,
                    "period_budget": row.period_budget,
                    "days_left": left,
                }
            )
    return alerts


def render_budget_pacing(
    rows: list[ads.BudgetPacingRow],
    *,
    as_of: date,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    left = days_left_in_month(as_of)
    lines = [
        f"_Updated {now:%Y-%m-%d %H:%M UTC}_",
        "",
        "## How to read this",
        "",
        "Google Ads does not spend more than the campaign budget over the configured "
        "period, but may front-load (including spending a large share of the period "
        "budget in a single day) to optimize performance. This page tracks "
        "**month-to-date spend versus the period budget** — not whether a single day "
        "looks high.",
        "",
        f"- **As of:** {as_of.isoformat()} (MTD)",
        f"- **Days left in month:** {left}",
        "",
        "## Pacing",
        "",
    ]
    if not rows:
        lines.append("_No campaign spend rows returned._\n")
        return "\n".join(lines)

    lines.extend(
        [
            "| Campaign | Type | Status | Period budget | MTD spend | % used | Remaining |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        pct = f"{row.percent_used:.1f}%" if row.percent_used is not None else "—"
        remaining = (
            ads.format_currency(max(0.0, row.period_budget - row.spend))
            if row.period_budget > 0
            else "—"
        )
        lines.append(
            f"| {row.name} | {row.channel_type} | {row.status} | "
            f"{ads.format_currency(row.period_budget)} | "
            f"{ads.format_currency(row.spend)} | {pct} | {remaining} |"
        )
    lines.append("")
    return "\n".join(lines)
