"""Feature Usage — per-feature event counts (L7D / L30D) for matched tracking.

SDK: Neither (deterministic HogQL → Markdown). Read-only at PostHog.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.product.posthog import posthog_client as ph
from company_brain.agents.product.posthog.feature_match import (
    match_features,
    parse_feature_titles,
)
from company_brain.wiki.publish import UPDATE, read_wiki_page, write_wiki_page

WIKI_PATH = "product/posthog/feature-usage.md"
TITLE = "Feature Usage"
FEATURE_WIKI = "product/feature.md"
WRITE_MODE = UPDATE


class FeatureUsageAgent(BaseAgent):
    """Overwrite the feature-usage table for matched wiki features."""

    name = "feature_usage"
    WRITE_MODE = WRITE_MODE

    def should_run(self, **kwargs: Any) -> bool:
        return ph.posthog_is_configured()

    def run(self, *, lookback_days: int | None = None, **kwargs: Any) -> dict[str, Any]:
        """``lookback_days`` caps the long window (default 30; onboarding may pass 30)."""
        long_days = int(lookback_days) if lookback_days is not None else 30
        long_days = max(1, long_days)
        short_days = min(7, long_days)

        features = parse_feature_titles(read_wiki_page(FEATURE_WIKI))
        flags = ph.list_feature_flags()
        events = ph.list_event_definitions()
        rows, _orphans = match_features(
            features,
            [f.key for f in flags],
            [e.name for e in events],
        )
        matched = [r for r in rows if r.status == "matched"]
        event_names = sorted({e for r in matched for e in r.event_names})

        counts_short = (
            ph.event_counts(event_names=event_names, days=short_days) if event_names else {}
        )
        counts_long = (
            ph.event_counts(event_names=event_names, days=long_days) if event_names else {}
        )

        usage_rows: list[dict[str, Any]] = []
        for row in matched:
            c7 = sum(counts_short.get(e, 0) for e in row.event_names)
            c30 = sum(counts_long.get(e, 0) for e in row.event_names)
            usage_rows.append(
                {
                    "feature": row.feature,
                    "events": row.event_names,
                    "flags": row.flag_keys,
                    "l7d": c7,
                    "l30d": c30,
                }
            )

        body = render_feature_usage(
            usage_rows,
            short_days=short_days,
            long_days=long_days,
            unmatched=sum(1 for r in rows if r.status == "missing"),
        )
        write_wiki_page(
            WIKI_PATH,
            TITLE,
            body,
            mode=WRITE_MODE,
            section="product",
            type_="report",
        )
        return {
            "wiki_path": WIKI_PATH,
            "matched_features": len(usage_rows),
            "lookback_days": long_days,
        }


def render_feature_usage(
    rows: list[dict[str, Any]],
    *,
    short_days: int = 7,
    long_days: int = 30,
    unmatched: int = 0,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    lines = [
        f"_Updated {now:%Y-%m-%d %H:%M UTC}_",
        "",
        "Event counts for wiki features that matched PostHog event definitions "
        f"(L{short_days}D / L{long_days}D). Unmatched features stay on Tracking Audit.",
        "",
    ]
    if unmatched:
        lines.append(f"_Skipped {unmatched} unmatched feature(s) from Product Features._")
        lines.append("")
    lines.extend(["## Usage", ""])
    if not rows:
        lines.append("_No matched features with event definitions._\n")
        return "\n".join(lines)

    lines.extend(
        [
            f"| Feature | Events | L{short_days}D | L{long_days}D | Flags |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        events = ", ".join(f"`{e}`" for e in row.get("events") or []) or "—"
        flags = ", ".join(f"`{k}`" for k in row.get("flags") or []) or "—"
        lines.append(
            f"| {row['feature']} | {events} | {int(row.get('l7d') or 0)} | "
            f"{int(row.get('l30d') or 0)} | {flags} |"
        )
    lines.append("")
    return "\n".join(lines)
