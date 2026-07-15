"""Monthly token budget, usage tracking, and per-run limit resolution.

Wired:
- ``check_budget()`` — hard-stop gate before each LLM run (when enabled).
- ``record_usage()`` — accumulates token counts + estimated USD in ``StateStore``.
- ``budget_status()`` — surfaced by ``company-brain doctor llm``.

Spend categories (``config/models.yaml`` ``spend_categories``):
- ``runtime`` — specialist agents running the product (default).
- ``builder`` — cloud coding agent that edits 4r7a from human feedback.

Both roll into the same ``token_budget.monthly_usd`` pool; ``guidance_usd`` is
doctor-only soft targets.

Per-run caps (``run_limits``) are enforced via ``llm/run_budget.py`` in
``BaseAgent.execute()`` and LLM SDK hooks — not in prompts.

Fallback reconciliation: finance ``card_spend`` vendor bills (see ``docs/tabled.md``).

When ``COMPANY_BRAIN_LLM_PROVIDER=glm`` (self-hosted GLM-5), consider Ramp Labs
**Latent Briefing** for manager→specialist KV-cache handoffs (~65% token savings).
Requires internal model access; not applicable to hosted API-only stacks.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.gates import StateStore
from company_brain.config import (
    ModelsConfig,
    RunLimitValues,
    load_models_config,
)

logger = logging.getLogger(__name__)

USAGE_PREFIX = "llm_budget:usage:"
ALERT_PREFIX = "llm_budget:alert:"

SPEND_RUNTIME = "runtime"
SPEND_BUILDER = "builder"
VALID_SPEND_CATEGORIES = frozenset({SPEND_RUNTIME, SPEND_BUILDER})

DEFAULT_MODEL_RATES: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input_per_million": 15.0, "output_per_million": 75.0},
    "claude-sonnet-4-6": {"input_per_million": 3.0, "output_per_million": 15.0},
    "claude-haiku-4-5": {"input_per_million": 0.80, "output_per_million": 4.0},
    "gpt-5.5": {"input_per_million": 2.50, "output_per_million": 10.0},
    "gpt-4.1": {"input_per_million": 2.0, "output_per_million": 8.0},
    "gpt-4.1-mini": {"input_per_million": 0.40, "output_per_million": 1.60},
    "glm-5": {"input_per_million": 0.0, "output_per_million": 0.0},
    "default": {"input_per_million": 3.0, "output_per_million": 15.0},
}

DEFAULT_TIER_RUN_LIMITS: dict[str, dict[str, float | int]] = {
    "fast": {
        "max_usd_per_run": 0.15,
        "max_steps_per_run": 10,
        "max_tool_calls_per_run": 15,
    },
    "standard": {
        "max_usd_per_run": 0.50,
        "max_steps_per_run": 20,
        "max_tool_calls_per_run": 40,
    },
    "reasoning": {
        "max_usd_per_run": 2.00,
        "max_steps_per_run": 35,
        "max_tool_calls_per_run": 80,
    },
}

DEFAULT_AGENT_RUN_LIMITS: dict[str, dict[str, float | int]] = {
    "absorb": {
        "max_usd_per_run": 8.00,
        "max_steps_per_run": 50,
        "max_tool_calls_per_run": 120,
    },
    "draft_reply": {"max_usd_per_run": 0.40, "max_tool_calls_per_run": 25},
    "budget_report": {"max_usd_per_run": 1.50},
    "subscription_audit": {"max_usd_per_run": 1.00},
    "card_spend": {"max_usd_per_run": 0.75},
}


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
        "guidance_usd": dict(spec.guidance_usd or {}),
    }


def resolve_spend_category(agent: str, cfg: ModelsConfig | None = None) -> str:
    """Return ``runtime`` or ``builder`` for an agent name."""
    cfg = cfg or load_models_config()
    sc = cfg.spend_categories
    raw = (sc.agents or {}).get(agent) or sc.default or SPEND_RUNTIME
    if raw not in VALID_SPEND_CATEGORIES:
        return SPEND_RUNTIME
    return raw


def _merge_limit_values(*layers: RunLimitValues | None) -> RunLimitValues:
    merged: dict[str, float | int | None] = {}
    for layer in layers:
        if layer is None:
            continue
        for field in ("max_usd_per_run", "max_steps_per_run", "max_tool_calls_per_run"):
            val = getattr(layer, field, None)
            if val is not None:
                merged[field] = val
    return RunLimitValues(**merged)


def resolve_run_limits(agent: str, cfg: ModelsConfig | None = None) -> RunLimitValues:
    """Merge defaults ← tier ← per-agent ← builder profile when category is builder."""
    from company_brain.llm.tiers import LLM_AGENTS, agent_tier, resolve_llm_agent_key

    cfg = cfg or load_models_config()
    rl = cfg.run_limits
    llm_key = resolve_llm_agent_key(agent) or agent
    tier_key = llm_key if llm_key in {**LLM_AGENTS, **(cfg.agents or {})} else agent
    tier = agent_tier(tier_key, cfg)
    category = resolve_spend_category(llm_key, cfg)

    tier_limits = (rl.tiers or {}).get(tier)
    if tier_limits is None and tier in DEFAULT_TIER_RUN_LIMITS:
        tier_limits = RunLimitValues(**DEFAULT_TIER_RUN_LIMITS[tier])

    agent_limits = (rl.agents or {}).get(llm_key)
    if agent_limits is None and llm_key in DEFAULT_AGENT_RUN_LIMITS:
        agent_limits = RunLimitValues(**DEFAULT_AGENT_RUN_LIMITS[llm_key])

    builder_layer = rl.builder if category == SPEND_BUILDER else None
    return _merge_limit_values(rl.defaults, tier_limits, agent_limits, builder_layer)


def _rate_for_model(model: str, cfg: ModelsConfig) -> tuple[float, float] | None:
    """Return (input, output) per-million rates, or None when the model is unknown.

    Unknown models must not fall through to a silent default price (misleading $0
    or a generic rate). Self-hosted entries like ``glm-5`` with explicit $0 rates
    still resolve as known.
    """
    key = (model or "").strip().lower()
    if not key:
        return None
    rates = cfg.model_rates or {}
    if key in rates:
        spec = rates[key]
        return float(spec.input_per_million), float(spec.output_per_million)
    for name, spec in rates.items():
        if name != "default" and key.startswith(name.lower()):
            return float(spec.input_per_million), float(spec.output_per_million)
    if key in DEFAULT_MODEL_RATES:
        fallback = DEFAULT_MODEL_RATES[key]
        return float(fallback["input_per_million"]), float(fallback["output_per_million"])
    return None


def model_rate_known(model: str, *, cfg: ModelsConfig | None = None) -> bool:
    cfg = cfg or load_models_config()
    return _rate_for_model(model, cfg) is not None


def estimate_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cfg: ModelsConfig | None = None,
    cache_read_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> float | None:
    """Estimate USD from token counts, or ``None`` when the model rate is unknown.

    Cache-read tokens are priced at the input rate when present. Reasoning tokens
    use the output rate (provider bills them as completion-class).
    """
    cfg = cfg or load_models_config()
    rates = _rate_for_model(model, cfg)
    if rates is None:
        return None
    inp_rate, out_rate = rates
    billable_in = input_tokens + max(cache_read_tokens, 0)
    billable_out = output_tokens + max(reasoning_tokens, 0)
    return (billable_in / 1_000_000) * inp_rate + (billable_out / 1_000_000) * out_rate


def _usage_key(when: datetime | None = None) -> str:
    return f"{USAGE_PREFIX}{_month_key(when)}"


def _token_dims(block: dict[str, Any]) -> dict[str, float]:
    return {
        "input_tokens": float(block.get("input_tokens") or 0),
        "output_tokens": float(block.get("output_tokens") or 0),
        "cache_read_tokens": float(block.get("cache_read_tokens") or 0),
        "cache_write_tokens": float(block.get("cache_write_tokens") or 0),
        "reasoning_tokens": float(block.get("reasoning_tokens") or 0),
        "estimated_usd": float(block.get("estimated_usd") or 0),
        "unknown_model_calls": float(block.get("unknown_model_calls") or 0),
    }


def current_usage(*, store: StateStore | None = None) -> dict[str, Any]:
    store = store or StateStore()
    raw = store.get(_usage_key()) or {}
    categories = raw.get("categories") or {}
    agents = raw.get("agents") or {}
    return {
        **_token_dims(raw),
        "categories": {name: _token_dims(block) for name, block in categories.items()},
        "agents": {
            name: {
                **_token_dims(block),
                "managers": {
                    mgr: _token_dims(mblock)
                    for mgr, mblock in (block.get("managers") or {}).items()
                },
            }
            for name, block in agents.items()
        },
    }


def budget_status(*, store: StateStore | None = None) -> dict[str, Any]:
    spec = budget_spec()
    usage = current_usage(store=store)
    limit = spec["monthly_usd"]
    spent = usage["estimated_usd"]
    pct = (spent / limit * 100) if limit > 0 else 0.0
    guidance = spec.get("guidance_usd") or {}
    cats = usage.get("categories") or {}
    return {
        "enabled": spec["enabled"],
        "month": _month_key(),
        "limit_usd": limit,
        "spent_usd": spent,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "percent_used": round(pct, 1),
        "hard_stop": spec["hard_stop"],
        "over_budget": spec["enabled"] and spent >= limit,
        "near_limit": spec["enabled"] and pct >= spec["alert_threshold_percent"],
        "guidance_usd": guidance,
        "runtime_usd": float((cats.get(SPEND_RUNTIME) or {}).get("estimated_usd") or 0),
        "builder_usd": float((cats.get(SPEND_BUILDER) or {}).get("estimated_usd") or 0),
        "categories": cats,
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


def _add_dims(
    block: dict[str, Any],
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    reasoning_tokens: int,
    cost: float | None,
    unknown: bool,
) -> None:
    block["input_tokens"] = float(block.get("input_tokens") or 0) + input_tokens
    block["output_tokens"] = float(block.get("output_tokens") or 0) + output_tokens
    block["cache_read_tokens"] = float(block.get("cache_read_tokens") or 0) + cache_read_tokens
    block["cache_write_tokens"] = float(block.get("cache_write_tokens") or 0) + cache_write_tokens
    block["reasoning_tokens"] = float(block.get("reasoning_tokens") or 0) + reasoning_tokens
    if cost is not None:
        block["estimated_usd"] = float(block.get("estimated_usd") or 0) + cost
    if unknown:
        block["unknown_model_calls"] = float(block.get("unknown_model_calls") or 0) + 1


def record_usage(
    *,
    agent: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    reasoning_tokens: int = 0,
    usd: float | None = None,
    spend_category: str | None = None,
    store: StateStore | None = None,
) -> dict[str, Any]:
    """Accumulate one LLM call into the monthly usage ledger.

    Inherits ambient ``run_id`` / ``manager`` / ``session_id`` from
    :mod:`company_brain.llm.run_context` when set. Unknown models leave
    ``estimated_usd`` unset for that call (tokens still accumulate).

    Returns the delta recorded for this call (tokens + usd / unknown flag).
    """
    dims_sum = (
        input_tokens
        + output_tokens
        + cache_read_tokens
        + cache_write_tokens
        + reasoning_tokens
    )
    if dims_sum <= 0 and (usd is None or usd <= 0):
        return {
            "input_tokens": 0.0,
            "output_tokens": 0.0,
            "cache_read_tokens": 0.0,
            "cache_write_tokens": 0.0,
            "reasoning_tokens": 0.0,
            "estimated_usd": None,
            "unknown_model": False,
        }

    store = store or StateStore()
    category = spend_category or resolve_spend_category(agent)
    if category not in VALID_SPEND_CATEGORIES:
        category = SPEND_RUNTIME

    if usd is not None:
        cost: float | None = float(usd)
        unknown = False
    else:
        cost = estimate_usd(
            model,
            input_tokens,
            output_tokens,
            cache_read_tokens=cache_read_tokens,
            reasoning_tokens=reasoning_tokens,
        )
        unknown = cost is None
        if unknown:
            logger.warning(
                "LLM usage for unknown model %r (agent=%s) — tokens recorded, "
                "estimated_usd left unset",
                model,
                agent,
            )

    from company_brain.llm.run_context import get_run_context

    ambient = get_run_context()
    manager = ambient.manager if ambient else None

    key = _usage_key()
    raw = dict(store.get(key) or {})
    _add_dims(
        raw,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
        cost=cost,
        unknown=unknown,
    )

    categories = dict(raw.get("categories") or {})
    cat_block = dict(categories.get(category) or {})
    _add_dims(
        cat_block,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
        cost=cost,
        unknown=unknown,
    )
    categories[category] = cat_block
    raw["categories"] = categories

    agents = dict(raw.get("agents") or {})
    agent_block = dict(agents.get(agent) or {})
    _add_dims(
        agent_block,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
        cost=cost,
        unknown=unknown,
    )
    if manager:
        managers = dict(agent_block.get("managers") or {})
        mgr_block = dict(managers.get(manager) or {})
        _add_dims(
            mgr_block,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            reasoning_tokens=reasoning_tokens,
            cost=cost,
            unknown=unknown,
        )
        managers[manager] = mgr_block
        agent_block["managers"] = managers
    if ambient:
        agent_block["last_run_id"] = ambient.run_id
        if ambient.session_id:
            agent_block["last_session_id"] = ambient.session_id
        if ambient.reason:
            agent_block["last_reason"] = ambient.reason
    agents[agent] = agent_block
    raw["agents"] = agents
    store.set(key, raw)

    logger.debug(
        "LLM usage +%d in / +%d out / +%d cache_r / +%d reason "
        "($%s) agent=%s manager=%s category=%s model=%s",
        input_tokens,
        output_tokens,
        cache_read_tokens,
        reasoning_tokens,
        f"{cost:.4f}" if cost is not None else "—",
        agent,
        manager,
        category,
        model,
    )
    maybe_alert_budget(store=store)

    from company_brain.llm.run_budget import agent_matches_run, get_run_budget

    run_budget = get_run_budget()
    if run_budget is not None and agent_matches_run(run_budget, agent) and cost is not None:
        run_budget.add_cost(float(cost))

    return {
        "input_tokens": float(input_tokens),
        "output_tokens": float(output_tokens),
        "cache_read_tokens": float(cache_read_tokens),
        "cache_write_tokens": float(cache_write_tokens),
        "reasoning_tokens": float(reasoning_tokens),
        "estimated_usd": float(cost) if cost is not None else None,
        "unknown_model": unknown,
        "manager": manager,
        "run_id": ambient.run_id if ambient else None,
        "session_id": ambient.session_id if ambient else None,
    }


def maybe_alert_budget(*, store: StateStore | None = None) -> bool:
    """Post a one-time near-limit alert to ``#wiki-admin`` when threshold crossed."""
    status = budget_status(store=store)
    if not status["enabled"] or not status["near_limit"] or status["over_budget"]:
        return False

    store = store or StateStore()
    alert_key = f"{ALERT_PREFIX}{status['month']}"
    if store.get(alert_key):
        return False

    from company_brain.llm.admin_notify import wiki_admin_notifier
    from company_brain.notify import ALERT, Signal

    guidance = status.get("guidance_usd") or {}
    runtime_guidance = guidance.get(SPEND_RUNTIME, 0)
    builder_guidance = guidance.get(SPEND_BUILDER, 0)
    text = (
        f"LLM budget at {status['percent_used']}% for {status['month']}: "
        f"${status['spent_usd']:.2f} / ${status['limit_usd']:.2f} "
        f"(runtime ${status['runtime_usd']:.2f}"
    )
    if runtime_guidance:
        text += f" / ~${runtime_guidance:.0f} guidance"
    text += f", builder ${status['builder_usd']:.2f}"
    if builder_guidance:
        text += f" / ~${builder_guidance:.0f} guidance"
    text += ")."

    delivered = wiki_admin_notifier().emit(Signal(text=text, severity=ALERT))
    if delivered:
        store.set(alert_key, {"sent_at": datetime.now(timezone.utc).isoformat()})
    return delivered
