"""Monthly token budget for wiki LLM operations (gate + status).

Wired today:
- ``check_budget()`` — hard-stop gate called before each LLM run (fails open when
  the budget is disabled or usage is unknown).
- ``budget_status()`` — surfaced by ``company-brain doctor llm``.

Not wired yet (see ``docs/tabled.md`` → "Token budget usage tracking"): the
usage write-path. Two approaches to build there:
1. **Primary** — hook each LLM API response, accumulate ``input_tokens`` /
   ``output_tokens``, convert to USD via per-model rates.
2. **Fallback** — reconcile monthly against vendor bills via finance ``card_spend``
   (Anthropic / OpenAI charges), coarser but closes the loop for hard_stop.

Until the write-path exists, ``current_usage`` stays at $0 and the gate never fires.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.gates import StateStore
from company_brain.config import load_models_config

USAGE_PREFIX = "llm_budget:usage:"


def _month_key(when: datetime | None = None) -> str:
    now = when or datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def budget_spec() -> dict[str, Any]:
    cfg = load_models_config()
    spec = cfg.token_budget
    return {
        "enabled": spec.enabled,
        "monthly_usd": float(spec.monthly_usd),
        "alert_threshold_percent": int(spec.alert_threshold_percent),
        "hard_stop": spec.hard_stop,
        "admin_channel": spec.admin_channel or "#wiki-admin",
    }


def current_usage(*, store: StateStore | None = None) -> dict[str, float]:
    store = store or StateStore()
    raw = store.get(f"{USAGE_PREFIX}{_month_key()}") or {}
    return {
        "input_tokens": float(raw.get("input_tokens") or 0),
        "output_tokens": float(raw.get("output_tokens") or 0),
        "estimated_usd": float(raw.get("estimated_usd") or 0),
    }


def budget_status(*, store: StateStore | None = None) -> dict[str, Any]:
    spec = budget_spec()
    usage = current_usage(store=store)
    limit = spec["monthly_usd"]
    spent = usage["estimated_usd"]
    pct = (spent / limit * 100) if limit > 0 else 0.0
    return {
        "enabled": spec["enabled"],
        "month": _month_key(),
        "limit_usd": limit,
        "spent_usd": spent,
        "percent_used": round(pct, 1),
        "hard_stop": spec["hard_stop"],
        "over_budget": spec["enabled"] and spent >= limit,
        "near_limit": spec["enabled"] and pct >= spec["alert_threshold_percent"],
    }


class BudgetExceededError(RuntimeError):
    """Raised when hard_stop is enabled and the monthly budget is exhausted."""


def check_budget(*, agent: str = "", store: StateStore | None = None) -> None:
    """Raise ``BudgetExceededError`` when hard_stop blocks further LLM calls."""
    status = budget_status(store=store)
    if not status["enabled"]:
        return
    if status["hard_stop"] and status["over_budget"]:
        raise BudgetExceededError(
            f"Monthly LLM budget exhausted (${status['spent_usd']:.2f} / "
            f"${status['limit_usd']:.2f}). Adjust config/models.yaml token_budget "
            "or wait until next month.",
        )
