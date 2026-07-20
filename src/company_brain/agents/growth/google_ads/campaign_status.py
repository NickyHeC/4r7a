"""Campaign Status — Google Ads inventory snapshot (Search, PMax, other).

SDK: Neither (deterministic GAQL → Markdown). Read-only at the Ads source.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.google_ads import google_ads_client as ads
from company_brain.wiki.publish import UPDATE, write_wiki_page

WIKI_PATH = "growth/google-ads/campaign-status.md"
TITLE = "Campaign Status"
WRITE_MODE = UPDATE


class CampaignStatusAgent(BaseAgent):
    """Overwrite the campaign inventory wiki page from a live Ads snapshot."""

    name = "campaign_status"
    WRITE_MODE = WRITE_MODE

    def should_run(self, **kwargs: Any) -> bool:
        return ads.google_ads_is_configured()

    def run(self, **kwargs: Any) -> dict[str, Any]:
        rows = ads.list_campaigns()
        body = render_campaign_status(rows)
        write_wiki_page(
            WIKI_PATH,
            TITLE,
            body,
            mode=WRITE_MODE,
            section="growth",
            type_="report",
        )
        return {"wiki_path": WIKI_PATH, "campaigns": len(rows)}


def render_campaign_status(
    rows: list[ads.CampaignRow],
    *,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    lines = [
        f"_Updated {now:%Y-%m-%d %H:%M UTC}_",
        "",
        "Snapshot of non-removed Google Ads campaigns (Search, Performance Max, and others).",
        "",
        "## Campaigns",
        "",
    ]
    if not rows:
        lines.append("_No campaigns returned._\n")
        return "\n".join(lines)

    lines.extend(
        [
            "| Campaign | Type | Status | Start | End | Budget | Period |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        budget = ads.format_currency(ads.micros_to_currency(row.budget_amount_micros))
        period = row.budget_period.split(".")[-1] if row.budget_period else ""
        lines.append(
            f"| {row.name} | {row.channel_type} | {row.status} | "
            f"{row.start_date or '—'} | {row.end_date or '—'} | {budget} | {period or '—'} |"
        )
    lines.append("")
    return "\n".join(lines)
