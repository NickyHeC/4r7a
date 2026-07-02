"""Per-agent model tier resolution (strategy B: mixed providers).

Resolves ``(provider_key, model_id, tier)`` for an agent from ``config/models.yaml``:
``mode`` (performance vs balanced), ``agents`` tier map, ``agent_providers``,
``tiers``, and doctor-written ``overrides``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from company_brain.config import ModelsConfig, load_models_config
from company_brain.llm.provider import LLMProvider, resolve_provider

DEFAULT_TIER = "standard"
PERFORMANCE_MODE = "performance"
BALANCED_MODE = "balanced"

# Known LLM agents — used for defaults and doctor checks.
LLM_AGENTS: dict[str, str] = {
    "absorb": "reasoning",
    "draft_reply": "standard",
    "budget_report": "reasoning",
    "subscription_audit": "standard",
    "card_spend": "standard",
}

DEFAULT_AGENT_PROVIDERS: dict[str, str] = {
    "absorb": "anthropic",
    "draft_reply": "anthropic",
    "card_spend": "anthropic",
    "subscription_audit": "anthropic",
    "budget_report": "openai",
}


@dataclass(frozen=True)
class AgentModel:
    """Resolved model binding for one agent."""

    agent: str
    provider_key: str
    tier: str
    model_id: str


def agent_tier(agent: str, cfg: ModelsConfig | None = None) -> str:
    """Return the tier name for ``agent`` given the active ``mode``."""
    cfg = cfg or load_models_config()
    if (cfg.mode or BALANCED_MODE).lower() == PERFORMANCE_MODE:
        return "reasoning"
    agents = {**LLM_AGENTS, **(cfg.agents or {})}
    return agents.get(agent, DEFAULT_TIER)


def agent_provider_key(agent: str, cfg: ModelsConfig | None = None) -> str:
    """Return which provider drives ``agent`` (strategy B)."""
    cfg = cfg or load_models_config()
    providers = {**DEFAULT_AGENT_PROVIDERS, **(cfg.agent_providers or {})}
    return providers.get(agent, cfg.default_provider or "anthropic")


def _override_model(cfg: ModelsConfig, provider_key: str, tier: str) -> str | None:
    overrides = cfg.overrides or {}
    tiers = overrides.get("tiers") or {}
    provider_overrides = tiers.get(provider_key) or {}
    raw = provider_overrides.get(tier)
    return str(raw).strip() if raw else None


def tier_model_id(provider_key: str, tier: str, cfg: ModelsConfig | None = None) -> str:
    """Look up the configured model id for ``provider_key`` + ``tier``."""
    cfg = cfg or load_models_config()
    override = _override_model(cfg, provider_key, tier)
    if override:
        return override
    tiers = cfg.tiers or {}
    tier_map = tiers.get(tier) or {}
    model = tier_map.get(provider_key)
    if model:
        return model
    provider = resolve_provider(provider_key)
    if provider.model:
        return provider.model
    raise ValueError(
        f"No model configured for provider '{provider_key}' tier '{tier}'. "
        "Set config/models.yaml tiers or run company-brain models configure.",
    )


def fallback_chain(provider_key: str, tier: str, cfg: ModelsConfig | None = None) -> list[str]:
    """Ordered model ids to try when the primary is unavailable."""
    cfg = cfg or load_models_config()
    chains = cfg.fallback_chains or {}
    provider_chains = chains.get(provider_key) or {}
    configured = provider_chains.get(tier) or []
    if configured:
        return list(configured)
    primary = tier_model_id(provider_key, tier, cfg)
    return [primary]


def resolve_agent_model(agent: str, cfg: ModelsConfig | None = None) -> AgentModel:
    """Resolve provider, tier, and model id for ``agent``."""
    cfg = cfg or load_models_config()
    tier = agent_tier(agent, cfg)
    provider_key = agent_provider_key(agent, cfg)
    env_override = os.getenv("COMPANY_BRAIN_LLM_MODEL", "").strip()
    if env_override and agent == "default":
        model_id = env_override
    else:
        model_id = tier_model_id(provider_key, tier, cfg)
    return AgentModel(
        agent=agent,
        provider_key=provider_key,
        tier=tier,
        model_id=model_id,
    )


def resolve_agent_provider(agent: str, cfg: ModelsConfig | None = None) -> LLMProvider:
    """Return an ``LLMProvider`` with the per-agent model id bound."""
    binding = resolve_agent_model(agent, cfg)
    base = resolve_provider(binding.provider_key)
    return LLMProvider(
        key=base.key,
        sdk=base.sdk,
        model=binding.model_id,
        base_url=base.base_url,
        api_key=base.api_key,
    )


def set_tier_override(
    provider_key: str,
    tier: str,
    model_id: str,
    *,
    cfg: ModelsConfig | None = None,
) -> ModelsConfig:
    """Persist a doctor fallback override into ``models.yaml``."""
    cfg = cfg or load_models_config()
    overrides = dict(cfg.overrides or {})
    tiers = dict(overrides.get("tiers") or {})
    provider_overrides = dict(tiers.get(provider_key) or {})
    provider_overrides[tier] = model_id
    tiers[provider_key] = provider_overrides
    overrides["tiers"] = tiers
    return cfg.model_copy(update={"overrides": overrides})
