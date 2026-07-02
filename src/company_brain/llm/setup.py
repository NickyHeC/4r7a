"""Onboarding presets for ``config/models.yaml``."""

from __future__ import annotations

import click

from company_brain.config import CONFIG_DIR, ModelsConfig, load_models_config, save_models_config

PERFORMANCE = "performance"
BALANCED = "balanced"

BALANCED_AGENTS = {
    "absorb": "reasoning",
    "draft_reply": "standard",
    "budget_report": "reasoning",
    "subscription_audit": "standard",
    "card_spend": "standard",
}

DEFAULT_TIERS = {
    "fast": {"anthropic": "claude-haiku-4-5", "openai": "gpt-4.1-mini"},
    "standard": {"anthropic": "claude-sonnet-4-6", "openai": "gpt-4.1"},
    "reasoning": {"anthropic": "claude-opus-4-6", "openai": "gpt-5.5"},
}

DEFAULT_AGENT_PROVIDERS = {
    "absorb": "anthropic",
    "draft_reply": "anthropic",
    "card_spend": "anthropic",
    "subscription_audit": "anthropic",
    "budget_report": "openai",
}

DEFAULT_FALLBACK_CHAINS = {
    "anthropic": {
        "reasoning": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"],
        "standard": ["claude-sonnet-4-6", "claude-haiku-4-5"],
        "fast": ["claude-haiku-4-5"],
    },
    "openai": {
        "reasoning": ["gpt-5.5", "gpt-4.1"],
        "standard": ["gpt-4.1", "gpt-4.1-mini"],
        "fast": ["gpt-4.1-mini"],
    },
}


DEFAULT_PROVIDERS = {
    "anthropic": {"sdk": "claude", "model": None},
    "openai": {"sdk": "openai", "model": "gpt-5.5"},
    "glm": {"sdk": "openai", "model": "glm-5"},
}


def apply_mode(mode: str, *, config_dir=None) -> ModelsConfig:
    """Write onboarding mode choice into ``models.yaml``."""
    config_dir = config_dir or CONFIG_DIR
    cfg = load_models_config(config_dir)
    normalized = mode.strip().lower()
    if normalized not in (PERFORMANCE, BALANCED):
        raise ValueError(f"mode must be '{PERFORMANCE}' or '{BALANCED}'")

    agents = (
        {name: "reasoning" for name in BALANCED_AGENTS}
        if normalized == PERFORMANCE
        else dict(BALANCED_AGENTS)
    )

    from company_brain.config import ProviderSpec

    providers = cfg.providers or {k: ProviderSpec(**v) for k, v in DEFAULT_PROVIDERS.items()}

    updated = cfg.model_copy(
        update={
            "mode": normalized,
            "tiers": cfg.tiers or DEFAULT_TIERS,
            "agents": agents,
            "agent_providers": cfg.agent_providers or DEFAULT_AGENT_PROVIDERS,
            "fallback_chains": cfg.fallback_chains or DEFAULT_FALLBACK_CHAINS,
            "providers": providers,
            "overrides": {},
        },
    )
    save_models_config(updated, config_dir)
    return updated


def prompt_configure(*, config_dir=None) -> ModelsConfig:
    """Interactive onboarding prompt for model mode."""
    click.echo("\nLLM model mode for company-brain agents:\n")
    click.echo("  1) performance — most powerful tier for every LLM agent")
    click.echo("  2) balanced     — cost ↔ quality tradeoff (recommended)\n")
    choice = click.prompt("Choose mode [1/2]", default="2").strip()
    mode = PERFORMANCE if choice in ("1", "performance") else BALANCED
    cfg = apply_mode(mode, config_dir=config_dir)
    click.secho(f"Wrote config/models.yaml (mode={mode})", fg="green")
    return cfg
