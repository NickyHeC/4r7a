"""Acquisition Cost — Ads-reported CPA snapshot (MTD + last 30 days).

SDK: Neither (deterministic GAQL → Markdown). Read-only at the Ads source.

CPA here is Google Ads cost / Ads conversions. True product conversion CPA needs
engineering instrumentation and Ads conversion-action configuration (deferred).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.google_ads import google_ads_client as ads
from company_brain.wiki.publish import UPDATE, write_wiki_page

WIKI_PATH = "growth/google-ads/acquisition-cost.md"
TITLE = "Acquisition Cost"
WRITE_MODE = UPDATE


class AcquisitionCostAgent(BaseAgent):
    """Overwrite the acquisition-cost wiki page from a live Ads snapshot."""

    name = "acquisition_cost"
    WRITE_MODE = WRITE_MODE

    def should_run(self, **kwargs: Any) -> bool:
        return ads.google_ads_is_configured()

    def run(self, **kwargs: Any) -> dict[str, Any]:
        mtd = ads.list_acquisition_cost(during="THIS_MONTH")
        last_30 = ads.list_acquisition_cost(during="LAST_30_DAYS")
        body = render_acquisition_cost(mtd=mtd, last_30=last_30)
        write_wiki_page(
            WIKI_PATH,
            TITLE,
            body,
            mode=WRITE_MODE,
            section="growth",
            type_="report",
        )
        return {
            "wiki_path": WIKI_PATH,
            "mtd_campaigns": len(mtd),
            "last_30_campaigns": len(last_30),
        }


def _fmt_cpa(cpa: float | None) -> str:
    if cpa is None:
        return "unavailable"
    return ads.format_currency(cpa)


def _table(rows: list[ads.AcquisitionCostRow]) -> list[str]:
    if not rows:
        return ["_No rows._", ""]
    lines = [
        "| Campaign | Type | Cost | Conversions | CPA | Clicks | Impressions |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.name} | {row.channel_type} | "
            f"{ads.format_currency(ads.micros_to_currency(row.cost_micros))} | "
            f"{row.conversions:g} | {_fmt_cpa(row.cpa)} | "
            f"{row.clicks} | {row.impressions} |"
        )
    lines.append("")
    return lines


def render_acquisition_cost(
    *,
    mtd: list[ads.AcquisitionCostRow],
    last_30: list[ads.AcquisitionCostRow],
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    any_conversions = any(r.conversions > 0 for r in mtd) or any(r.conversions > 0 for r in last_30)
    lines = [
        f"_Updated {now:%Y-%m-%d %H:%M UTC}_",
        "",
        "Ads-reported cost per acquisition: **cost ÷ Google Ads conversions**. "
        "This is not yet product-true conversion CPA (requires engineering and Ads "
        "conversion setup).",
        "",
    ]
    if not any_conversions:
        lines.extend(
            [
                "> CPA unavailable — no conversions recorded in these windows. "
                "Cost, clicks, and impressions are still shown.",
                "",
            ]
        )

    lines.extend(["## Month to date", ""])
    lines.extend(_table(mtd))
    lines.extend(["## Last 30 days", ""])
    lines.extend(_table(last_30))
    return "\n".join(lines)
