"""Experiment Watch — PostHog A/B tests; flag conclusive winners.

SDK: Neither (deterministic private REST → Markdown). Read-only; never stops experiments.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import is_handled, mark_handled
from company_brain.agents.product.posthog import posthog_client as ph
from company_brain.agents.product.posthog import posthog_config as cfg
from company_brain.wiki.publish import UPDATE, write_wiki_page

WIKI_PATH = "product/posthog/experiment-watch.md"
TITLE = "Experiment Watch"
WRITE_MODE = UPDATE
NOTIFY_GATE = "posthog_experiment_watch:conclusive"


class ExperimentWatchAgent(BaseAgent):
    """Overwrite the experiment-watch page; surface newly conclusive tests."""

    name = "experiment_watch"
    WRITE_MODE = WRITE_MODE

    def should_run(self, **kwargs: Any) -> bool:
        return ph.posthog_is_configured()

    def run(self, **kwargs: Any) -> dict[str, Any]:
        experiments = [e for e in ph.list_experiments() if not e.archived]
        min_exp = cfg.min_exposures()
        threshold = cfg.probability_threshold()
        summaries: list[dict[str, Any]] = []
        newly_conclusive: list[dict[str, Any]] = []

        for exp in experiments:
            summary = summarize_experiment(
                exp.raw,
                name=exp.name,
                flag_key=exp.feature_flag_key,
                start_date=exp.start_date,
                end_date=exp.end_date,
                min_exposures=min_exp,
                probability_threshold=threshold,
            )
            summaries.append(summary)
            if summary.get("conclusive"):
                gate = f"{NOTIFY_GATE}:{exp.id}:{summary.get('winner') or 'win'}"
                if not is_handled(gate, "done"):
                    mark_handled(gate, "done")
                    newly_conclusive.append(summary)

        body = render_experiment_watch(summaries, min_exposures=min_exp, threshold=threshold)
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
            "experiments": len(summaries),
            "conclusive": [s for s in summaries if s.get("conclusive")],
            "newly_conclusive": newly_conclusive,
        }


def summarize_experiment(
    raw: dict[str, Any],
    *,
    name: str,
    flag_key: str,
    start_date: str,
    end_date: str,
    min_exposures: int,
    probability_threshold: float,
) -> dict[str, Any]:
    metrics = _extract_metrics(raw)
    exposures = [int(m.get("exposures") or 0) for m in metrics]
    enough = bool(exposures) and all(e >= min_exposures for e in exposures)
    significant = bool(raw.get("significant")) or _any_significant(raw)
    best_prob, winner = _best_probability(metrics)
    conclusive = False
    reason = "running"
    if end_date and not metrics:
        reason = "ended (no metrics in API payload)"
    elif enough and (significant or best_prob >= probability_threshold):
        conclusive = True
        reason = "significant" if significant else f"p≥{probability_threshold:.0%}"
    elif not enough:
        reason = f"below min exposures ({min_exposures})"

    return {
        "id": raw.get("id"),
        "name": name,
        "flag_key": flag_key,
        "start_date": start_date or "—",
        "end_date": end_date or "—",
        "exposures": exposures,
        "winner": winner or "—",
        "probability": best_prob,
        "conclusive": conclusive,
        "reason": reason,
    }


def _extract_metrics(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize variant metrics from heterogeneous experiment payloads."""
    out: list[dict[str, Any]] = []
    candidates = (
        raw.get("metrics"),
        raw.get("results"),
        (raw.get("stats") or {}).get("variants") if isinstance(raw.get("stats"), dict) else None,
    )
    for block in candidates:
        if isinstance(block, list):
            for item in block:
                if isinstance(item, dict):
                    out.append(_normalize_variant(item))
            if out:
                return out
        if isinstance(block, dict):
            for key, item in block.items():
                if isinstance(item, dict):
                    row = _normalize_variant(item)
                    row.setdefault("key", str(key))
                    out.append(row)
            if out:
                return out
    # parameters.variants sometimes only has keys
    params = raw.get("parameters") or {}
    variants = params.get("variants") if isinstance(params, dict) else None
    if isinstance(variants, list):
        for item in variants:
            if isinstance(item, dict):
                out.append(_normalize_variant(item))
    return out


def _normalize_variant(item: dict[str, Any]) -> dict[str, Any]:
    exposures = (
        item.get("exposures")
        or item.get("absolute_exposure")
        or item.get("sample_size")
        or item.get("count")
        or 0
    )
    prob = item.get("probability") or item.get("chance_to_win") or item.get("pi") or 0.0
    try:
        prob_f = float(prob)
    except (TypeError, ValueError):
        prob_f = 0.0
    if prob_f > 1.0:
        prob_f = prob_f / 100.0
    return {
        "key": str(item.get("key") or item.get("name") or item.get("variant") or ""),
        "exposures": int(exposures or 0),
        "probability": prob_f,
        "significant": bool(item.get("significant")),
    }


def _any_significant(raw: dict[str, Any]) -> bool:
    for m in _extract_metrics(raw):
        if m.get("significant"):
            return True
    return False


def _best_probability(metrics: list[dict[str, Any]]) -> tuple[float, str]:
    best = 0.0
    winner = ""
    for m in metrics:
        key = str(m.get("key") or "")
        if key.lower() in {"control", "c"}:
            continue
        prob = float(m.get("probability") or 0.0)
        if prob > best:
            best = prob
            winner = key
    return best, winner


def is_conclusive(
    raw: dict[str, Any],
    *,
    min_exposures: int = 100,
    probability_threshold: float = 0.95,
) -> bool:
    summary = summarize_experiment(
        raw,
        name=str(raw.get("name") or ""),
        flag_key="",
        start_date="",
        end_date="",
        min_exposures=min_exposures,
        probability_threshold=probability_threshold,
    )
    return bool(summary["conclusive"])


def render_experiment_watch(
    summaries: list[dict[str, Any]],
    *,
    min_exposures: int,
    threshold: float,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    lines = [
        f"_Updated {now:%Y-%m-%d %H:%M UTC}_",
        "",
        f"PostHog experiments (non-archived). Conclusive when significant **or** "
        f"best non-control probability ≥ {threshold:.0%} **and** every variant has "
        f"≥ {min_exposures} exposures. Agents never stop or ship experiments.",
        "",
        "## Experiments",
        "",
    ]
    if not summaries:
        lines.append("_No active experiments._\n")
        return "\n".join(lines)

    lines.extend(
        [
            "| Experiment | Flag | Start | End | Winner | P(win) | Status |",
            "| --- | --- | --- | --- | --- | ---: | --- |",
        ]
    )
    for s in summaries:
        flag = f"`{s['flag_key']}`" if s.get("flag_key") else "—"
        prob = s.get("probability") or 0.0
        status = "conclusive" if s.get("conclusive") else s.get("reason") or "running"
        lines.append(
            f"| {s.get('name') or '—'} | {flag} | {s.get('start_date')} | "
            f"{s.get('end_date')} | {s.get('winner') or '—'} | {prob:.0%} | {status} |"
        )
    lines.append("")
    return "\n".join(lines)
