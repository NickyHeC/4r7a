"""Tracking Audit — wiki Product Features vs PostHog flags/events.

SDK: Neither (deterministic private REST → Markdown). Read-only at PostHog.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import is_handled, mark_handled
from company_brain.agents.product.posthog import posthog_client as ph
from company_brain.agents.product.posthog.feature_match import (
    MatchRow,
    OrphanRow,
    match_features,
    parse_feature_titles,
)
from company_brain.wiki.publish import UPDATE, read_wiki_page, write_wiki_page

WIKI_PATH = "product/posthog/tracking-audit.md"
TITLE = "Tracking Audit"
FEATURE_WIKI = "product/feature.md"
WRITE_MODE = UPDATE
NOTIFY_GATE = "posthog_tracking_audit:missing"


class TrackingAuditAgent(BaseAgent):
    """Overwrite the tracking-audit table from feature.md × PostHog definitions."""

    name = "tracking_audit"
    WRITE_MODE = WRITE_MODE

    def should_run(self, **kwargs: Any) -> bool:
        return ph.posthog_is_configured()

    def run(self, **kwargs: Any) -> dict[str, Any]:
        features = parse_feature_titles(read_wiki_page(FEATURE_WIKI))
        flags = ph.list_feature_flags()
        events = ph.list_event_definitions()
        rows, orphans = match_features(
            features,
            [f.key for f in flags],
            [e.name for e in events],
        )
        body = render_tracking_audit(rows, orphans)
        write_wiki_page(
            WIKI_PATH,
            TITLE,
            body,
            mode=WRITE_MODE,
            section="product",
            type_="report",
        )
        missing = [r.feature for r in rows if r.status == "missing"]
        new_missing = _new_missing_for_notify(missing)
        return {
            "wiki_path": WIKI_PATH,
            "features": len(features),
            "matched": sum(1 for r in rows if r.status == "matched"),
            "missing": missing,
            "new_missing": new_missing,
            "orphans": len(orphans),
        }


def _new_missing_for_notify(missing: list[str]) -> list[str]:
    """Return missing features not yet ACTIONABLE-notified; mark them handled."""
    fresh: list[str] = []
    for feature in missing:
        sig = feature.strip().lower()
        if not sig:
            continue
        gate = f"{NOTIFY_GATE}:{sig}"
        if is_handled(gate, "done"):
            continue
        mark_handled(gate, "done")
        fresh.append(feature)
    return fresh


def render_tracking_audit(
    rows: list[MatchRow],
    orphans: list[OrphanRow],
    *,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    lines = [
        f"_Updated {now:%Y-%m-%d %H:%M UTC}_",
        "",
        "Heuristic match of [[product/feature|Product Features]] against PostHog "
        "feature flags and event definitions. Matched / missing / orphan — refine "
        "by aligning flag and event names with feature titles.",
        "",
        "## Feature coverage",
        "",
    ]
    if not rows:
        lines.append("_No features found in `product/feature.md`._\n")
    else:
        lines.extend(
            [
                "| Feature | Status | Flags | Events |",
                "| --- | --- | --- | --- |",
            ]
        )
        for row in rows:
            flags = ", ".join(f"`{k}`" for k in row.flag_keys) or "—"
            events = ", ".join(f"`{e}`" for e in row.event_names) or "—"
            lines.append(f"| {row.feature} | {row.status} | {flags} | {events} |")
        lines.append("")

    lines.extend(["## Orphan PostHog keys", ""])
    if not orphans:
        lines.append("_No unmatched flags/events (custom events only)._\n")
    else:
        lines.extend(["| Kind | Key |", "| --- | --- |"])
        for orphan in orphans:
            lines.append(f"| {orphan.kind} | `{orphan.key}` |")
        lines.append("")
    return "\n".join(lines)
