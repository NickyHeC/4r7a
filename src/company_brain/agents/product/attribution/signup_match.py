"""Signup Match — growth activity events vs signup spikes.

SDK: Neither (deterministic window matching). Pluggable signup source.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import is_handled, mark_handled
from company_brain.agents.product.attribution.signup_sources import (
    SignupEvent,
    load_signups,
    signup_source_signature,
)
from company_brain.agents.product.shared.product_slack import product_notifier
from company_brain.agents.product.shared.workstream_config import attribution_cfg
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

WIKI_PATH = "product/attribution/signup-match.md"
TITLE = "Signup Match"
EVENT_DIR = "growth/activity/event/"
WRITE_MODE = UPDATE


class SignupMatchAgent(BaseAgent):
    """Overwrite signup-match page; notify on new high-confidence matches."""

    name = "signup_match"
    WRITE_MODE = WRITE_MODE

    def run(self, *, force: bool = False, **kwargs: Any) -> dict[str, Any]:
        cfg = attribution_cfg()
        window = int(cfg.get("match_window_days") or 7)
        min_signups = int(cfg.get("min_signups_for_match") or 3)
        events = list_activity_events()
        signups = load_signups(days=max(30, window * 4))
        matches = match_activity_to_signups(
            events, signups, window_days=window, min_signups=min_signups
        )

        new_matches = []
        for m in matches:
            if m.get("confidence") != "high":
                continue
            sig = str(m.get("signature") or "")
            gate = f"signup_match:{m.get('slug')}"
            if force or not is_handled(gate, sig):
                new_matches.append(m)
                mark_handled(gate, sig)

        body = render_signup_match(matches, signup_count=len(signups), event_count=len(events))
        write_wiki_page(
            WIKI_PATH,
            TITLE,
            body,
            mode=WRITE_MODE,
            section="product",
            type_="report",
        )

        if new_matches:
            lines = ["Possible activity → signup spike matches (review attribution):"]
            for m in new_matches[:15]:
                lines.append(
                    f"• {m['event']} ({m['event_date']}): {m['signups']} signups "
                    f"within ±{window}d ({m['confidence']})"
                )
            product_notifier().emit(Signal(text="\n".join(lines), severity=ACTIONABLE))

        return {
            "wiki_path": WIKI_PATH,
            "matches": len(matches),
            "new_high_confidence": [m["event"] for m in new_matches],
            "signups": len(signups),
            "events": len(events),
        }


def activity_signup_signature() -> str:
    store = LocalWikiStore()
    parts = [signup_source_signature()]
    for rel in sorted(store.list(EVENT_DIR)):
        if rel.endswith(".md"):
            parts.append(rel)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def list_activity_events() -> list[dict[str, Any]]:
    store = LocalWikiStore()
    out: list[dict[str, Any]] = []
    for rel in store.list(EVENT_DIR):
        if not rel.endswith(".md"):
            continue
        doc = store.read(rel)
        fm = doc.frontmatter or {}
        raw_date = fm.get("event_date") or fm.get("date")
        when = None
        if raw_date:
            try:
                when = date.fromisoformat(str(raw_date)[:10])
            except ValueError:
                when = None
        slug = rel.rsplit("/", 1)[-1].removesuffix(".md")
        title = str(fm.get("title") or slug)
        out.append(
            {
                "slug": slug,
                "title": title,
                "date": when,
                "status": str(fm.get("event_status") or ""),
                "path": rel,
            }
        )
    return out


def match_activity_to_signups(
    events: list[dict[str, Any]],
    signups: list[SignupEvent],
    *,
    window_days: int,
    min_signups: int,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for event in events:
        when: date | None = event.get("date")
        if when is None:
            continue
        start = when - timedelta(days=window_days)
        end = when + timedelta(days=window_days)
        count = sum(1 for s in signups if start <= s.when <= end)
        if count < min_signups:
            continue
        # baseline: same-length window before the event window
        pre_end = start - timedelta(days=1)
        pre_start = pre_end - timedelta(days=window_days * 2)
        baseline = sum(1 for s in signups if pre_start <= s.when <= pre_end)
        confidence = "high" if count >= max(min_signups, baseline * 2, baseline + 3) else "low"
        sig = f"{event['slug']}:{when.isoformat()}:{count}"
        matches.append(
            {
                "event": event["title"],
                "slug": event["slug"],
                "event_date": when.isoformat(),
                "signups": count,
                "baseline": baseline,
                "confidence": confidence,
                "signature": sig,
                "path": event["path"],
            }
        )
    matches.sort(key=lambda m: (m["confidence"] != "high", -int(m["signups"])))
    return matches


def render_signup_match(
    matches: list[dict[str, Any]],
    *,
    signup_count: int,
    event_count: int,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    cfg = attribution_cfg()
    source = (cfg.get("signup_source") or {}).get("type") or "wiki_crm"
    lines = [
        f"_Updated {now:%Y-%m-%d %H:%M UTC}_",
        "",
        f"**Signup source:** `{source}` · **Signups (window):** {signup_count} · "
        f"**Activity events:** {event_count}",
        "",
        "Matches are time-window correlations only — not claimed ROI dollars.",
        "",
        "## Matches",
        "",
    ]
    if not matches:
        lines.append("_No activity/signup window matches above threshold._\n")
        return "\n".join(lines)

    lines.extend(
        [
            "| Event | Date | Signups in window | Baseline | Confidence |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    for m in matches:
        lines.append(
            f"| {m['event']} | {m['event_date']} | {m['signups']} | "
            f"{m['baseline']} | `{m['confidence']}` |"
        )
    lines.append("")
    return "\n".join(lines)
