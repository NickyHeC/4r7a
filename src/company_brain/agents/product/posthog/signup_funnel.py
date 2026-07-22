"""Signup Funnel — landing → create account conversion (L7D / L30D).

SDK: Neither (deterministic private REST / HogQL → Markdown). Read-only at PostHog.
Prefers a saved funnel insight by name; falls back to config step contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import is_handled, mark_handled
from company_brain.agents.product.posthog import posthog_client as ph
from company_brain.agents.product.posthog import posthog_config as cfg
from company_brain.wiki.publish import UPDATE, write_wiki_page

WIKI_PATH = "product/posthog/signup-funnel.md"
TITLE = "Signup Funnel"
WRITE_MODE = UPDATE
NOTIFY_GATE = "posthog_signup_funnel:zero_step"


class SignupFunnelAgent(BaseAgent):
    """Overwrite signup-funnel visits/conversions; alert once on empty expected steps."""

    name = "signup_funnel"
    WRITE_MODE = WRITE_MODE

    def should_run(self, **kwargs: Any) -> bool:
        return ph.posthog_is_configured()

    def run(self, *, lookback_days: int | None = None, **kwargs: Any) -> dict[str, Any]:
        long_days = int(lookback_days) if lookback_days is not None else 30
        long_days = max(1, long_days)
        short_days = min(7, long_days)

        insight_name = cfg.funnel_insight_name()
        insight = ph.find_insight_by_name(insight_name)
        source = "saved_insight" if insight else "config_fallback"

        short = _funnel_windows(short_days, insight=insight)
        long = _funnel_windows(long_days, insight=insight)

        zero_steps = [
            step["name"] for step in long.get("steps") or [] if int(step.get("count") or 0) == 0
        ]
        new_zero = _new_zero_for_notify(zero_steps)

        body = render_signup_funnel(
            short=short,
            long=long,
            short_days=short_days,
            long_days=long_days,
            source=source,
            insight_name=insight_name,
            dashboard_name=cfg.funnel_dashboard_name(),
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
            "source": source,
            "lookback_days": long_days,
            "zero_steps": zero_steps,
            "new_zero_steps": new_zero,
            "l7d": short,
            "l30d": long,
        }


def _new_zero_for_notify(zero_steps: list[str]) -> list[str]:
    fresh: list[str] = []
    for step in zero_steps:
        sig = step.strip().lower()
        if not sig:
            continue
        gate = f"{NOTIFY_GATE}:{sig}"
        if is_handled(gate, "done"):
            continue
        mark_handled(gate, "done")
        fresh.append(step)
    return fresh


def _funnel_windows(days: int, *, insight: dict[str, Any] | None) -> dict[str, Any]:
    if insight:
        parsed = _steps_from_insight(insight, days=days)
        if parsed.get("steps"):
            return parsed
    return _steps_from_config(days=days)


def _steps_from_config(*, days: int) -> dict[str, Any]:
    landing = ph.pageview_count(paths=cfg.landing_paths(), days=days)
    signup_name = cfg.signup_event()
    counts = ph.event_counts(event_names=[signup_name], days=days)
    signup = int(counts.get(signup_name) or 0)
    rate = (signup / landing * 100.0) if landing > 0 else None
    return {
        "steps": [
            {"name": "Landing pageview", "event": "$pageview", "count": landing},
            {"name": "Create account", "event": signup_name, "count": signup},
        ],
        "conversion_rate": rate,
    }


def _steps_from_insight(insight: dict[str, Any], *, days: int) -> dict[str, Any]:
    """Best-effort: use insight query steps for names, HogQL for counts."""
    query = insight.get("query") or insight.get("filters") or {}
    step_defs = _insight_step_defs(query)
    if not step_defs:
        return {"steps": [], "conversion_rate": None}

    steps: list[dict[str, Any]] = []
    for step in step_defs:
        event = step.get("event") or ""
        name = step.get("name") or event or "step"
        if event == "$pageview" or step.get("kind") == "pageview":
            count = ph.pageview_count(paths=cfg.landing_paths(), days=days)
        elif event:
            count = int(ph.event_counts(event_names=[event], days=days).get(event) or 0)
        else:
            count = 0
        steps.append({"name": name, "event": event or "—", "count": count})

    first = int(steps[0]["count"]) if steps else 0
    last = int(steps[-1]["count"]) if steps else 0
    rate = (last / first * 100.0) if first > 0 else None
    return {"steps": steps, "conversion_rate": rate}


def _insight_step_defs(query: Any) -> list[dict[str, Any]]:
    if not isinstance(query, dict):
        return []
    # FunnelsQuery shape
    series = query.get("series") or query.get("events") or []
    if isinstance(query.get("query"), dict):
        inner = query["query"]
        series = series or inner.get("series") or inner.get("events") or []
    out: list[dict[str, Any]] = []
    if isinstance(series, list):
        for idx, item in enumerate(series):
            if not isinstance(item, dict):
                continue
            event = str(item.get("event") or item.get("id") or "").strip()
            custom = str(item.get("custom_name") or item.get("name") or "").strip()
            out.append(
                {
                    "name": custom or event or f"Step {idx + 1}",
                    "event": event,
                    "kind": "pageview" if event == "$pageview" else "event",
                }
            )
    return out


def render_signup_funnel(
    *,
    short: dict[str, Any],
    long: dict[str, Any],
    short_days: int,
    long_days: int,
    source: str,
    insight_name: str,
    dashboard_name: str,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    source_note = (
        f"Using saved PostHog insight `{insight_name}`."
        if source == "saved_insight"
        else (
            f"No saved funnel named `{insight_name}` — using config defaults "
            f"(landing paths → `{cfg.signup_event()}`). "
            f"Optional dashboard: `{dashboard_name}`."
        )
    )
    lines = [
        f"_Updated {now:%Y-%m-%d %H:%M UTC}_",
        "",
        "Landing on the website → creating an account. Instrumentation lives in "
        "PostHog; this page mirrors counts only.",
        "",
        source_note,
        "",
        f"## Last {short_days} days",
        "",
    ]
    lines.extend(_render_window(short))
    lines.extend(["", f"## Last {long_days} days", ""])
    lines.extend(_render_window(long))
    lines.append("")
    return "\n".join(lines)


def _render_window(window: dict[str, Any]) -> list[str]:
    steps = list(window.get("steps") or [])
    if not steps:
        return ["_No funnel steps available._"]
    lines = [
        "| Step | Event | Count |",
        "| --- | --- | ---: |",
    ]
    for step in steps:
        lines.append(
            f"| {step.get('name')} | `{step.get('event')}` | {int(step.get('count') or 0)} |"
        )
    rate = window.get("conversion_rate")
    if rate is None:
        lines.append("")
        lines.append("Overall conversion: —")
    else:
        lines.append("")
        lines.append(f"Overall conversion: **{rate:.1f}%**")
    return lines
