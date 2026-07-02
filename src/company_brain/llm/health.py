"""Model health checks + auto-fallback within configured chains."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from company_brain.agents.gates import StateStore
from company_brain.config import CONFIG_DIR, ModelsConfig, load_models_config, save_models_config
from company_brain.llm.admin_notify import wiki_admin_notifier
from company_brain.llm.tiers import (
    LLM_AGENTS,
    agent_provider_key,
    agent_tier,
    fallback_chain,
    set_tier_override,
    tier_model_id,
)
from company_brain.notify import ACTIONABLE, Signal

logger = logging.getLogger(__name__)

HEALTH_STAMP_KEY = "llm_health:last_run"


@dataclass
class ModelProbeResult:
    provider_key: str
    tier: str
    model_id: str
    ok: bool
    detail: str = ""


@dataclass
class ModelHealthReport:
    probes: list[ModelProbeResult] = field(default_factory=list)
    fallbacks_applied: list[str] = field(default_factory=list)
    alerts_sent: int = 0


def _anthropic_configured() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def _openai_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _provider_configured(provider_key: str) -> bool:
    if provider_key == "anthropic":
        return _anthropic_configured()
    if provider_key == "openai":
        return _openai_configured()
    if provider_key == "glm":
        return bool(os.getenv("GLM_BASE_URL", "").strip())
    return False


def ping_model(provider_key: str, model_id: str) -> tuple[bool, str]:
    """Return ``(ok, detail)`` for a minimal provider ping."""
    if not _provider_configured(provider_key):
        return False, f"{provider_key} credentials not configured"

    try:
        if provider_key == "anthropic":
            return _ping_anthropic(model_id)
        if provider_key in ("openai", "glm"):
            return _ping_openai_compatible(provider_key, model_id)
    except Exception as exc:
        return False, str(exc)
    return False, f"unknown provider '{provider_key}'"


def _ping_anthropic(model_id: str) -> tuple[bool, str]:
    import anthropic

    client = anthropic.Anthropic()
    client.messages.create(
        model=model_id,
        max_tokens=1,
        messages=[{"role": "user", "content": "ping"}],
    )
    return True, "ok"


def _ping_openai_compatible(provider_key: str, model_id: str) -> tuple[bool, str]:
    from openai import OpenAI

    from company_brain.llm.provider import resolve_provider

    provider = resolve_provider(provider_key)
    client = OpenAI(
        api_key=provider.api_key or "not-needed",
        base_url=provider.base_url,
    )
    client.chat.completions.create(
        model=model_id,
        max_tokens=1,
        messages=[{"role": "user", "content": "ping"}],
    )
    return True, "ok"


def run_model_health(
    *,
    apply_fallbacks: bool = True,
    notify: bool = True,
    cfg: ModelsConfig | None = None,
) -> ModelHealthReport:
    """Probe each agent's resolved model; fall back and alert on failure."""
    cfg = cfg or load_models_config()
    report = ModelHealthReport()
    seen: set[tuple[str, str, str]] = set()
    updated_cfg = cfg

    for agent in LLM_AGENTS:
        provider_key = agent_provider_key(agent, cfg)
        tier = agent_tier(agent, cfg)
        primary = tier_model_id(provider_key, tier, cfg)
        key = (provider_key, tier, primary)
        if key not in seen:
            seen.add(key)
            ok, detail = ping_model(provider_key, primary)
            report.probes.append(
                ModelProbeResult(provider_key, tier, primary, ok, detail),
            )
            if not ok and apply_fallbacks:
                replacement = _apply_fallback(
                    provider_key, tier, primary, cfg=updated_cfg,
                )
                if replacement:
                    updated_cfg = replacement["cfg"]
                    report.fallbacks_applied.append(replacement["message"])
                    if notify:
                        _alert_fallback(replacement["message"])
                        report.alerts_sent += 1

    if apply_fallbacks and updated_cfg != cfg:
        save_models_config(updated_cfg, CONFIG_DIR)

    StateStore().set(HEALTH_STAMP_KEY, datetime.now(timezone.utc).isoformat())
    return report


def _apply_fallback(
    provider_key: str,
    tier: str,
    failed_model: str,
    *,
    cfg: ModelsConfig,
) -> dict | None:
    for candidate in fallback_chain(provider_key, tier, cfg):
        if candidate == failed_model:
            continue
        ok, _ = ping_model(provider_key, candidate)
        if ok:
            new_cfg = set_tier_override(provider_key, tier, candidate, cfg=cfg)
            msg = (
                f"Model health: {provider_key}/{tier} "
                f"'{failed_model}' unavailable → using '{candidate}'"
            )
            logger.warning(msg)
            return {"cfg": new_cfg, "message": msg}
    return None


def _alert_fallback(message: str) -> None:
    try:
        wiki_admin_notifier().emit(
            Signal(text=message, severity=ACTIONABLE),
        )
    except Exception:
        logger.exception("Failed to send model health alert")
