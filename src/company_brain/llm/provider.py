"""LLM provider resolution — the single knob that switches the model behind
every agent.

company-brain runs its agents on **two** agent SDKs (see the ``agent-construction``
rule): the Anthropic Claude Agent SDK (MCP-native, big-context "do-it-all"
agents) and the OpenAI Agents SDK (provider-flexible specialist workflows). This
module resolves the active provider from ``config/models.yaml`` + environment and
hands each SDK what it needs.

Providers (declared in ``config/models.yaml``):

* ``anthropic`` — hosted Anthropic API (``sdk: claude``). Default for local
  installs; needs only ``ANTHROPIC_API_KEY``.
* ``openai`` — hosted OpenAI API (``sdk: openai``). Needs ``OPENAI_API_KEY``.
* ``glm`` — open-source GLM-5 served behind an OpenAI-compatible endpoint
  (``sdk: openai``): self-hosted on the cloud GPU VM, or a remote open-source
  host you connect to. No external tokens are billed. Requires ``GLM_BASE_URL``.

Endpoints and secrets always come from the environment — never hardcoded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from company_brain.config import load_models_config, resolve_llm_provider

# Per-provider environment variables for the endpoint and credential. Anthropic
# and OpenAI base URLs are optional overrides (the SDKs default to the hosted
# API); GLM requires an explicit endpoint.
_BASE_URL_ENV = {
    "anthropic": "ANTHROPIC_BASE_URL",
    "openai": "OPENAI_BASE_URL",
    "glm": "GLM_BASE_URL",
}
_API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "glm": "GLM_API_KEY",
}


@dataclass(frozen=True)
class LLMProvider:
    """Resolved provider: which SDK drives it, the model id, endpoint, and key."""

    key: str  # "anthropic" | "openai" | "glm" | custom
    sdk: str  # "claude" | "openai" — which agent SDK to drive
    model: str | None  # model id (None -> SDK default; only meaningful for claude)
    base_url: str | None  # OpenAI-compatible / Anthropic gateway endpoint
    api_key: str | None

    @property
    def is_open_source(self) -> bool:
        """True for a self-hosted/remote open-source endpoint (e.g. GLM-5)."""
        return self.key == "glm"


def resolve_provider(name: str | None = None) -> LLMProvider:
    """Resolve the active provider.

    ``name`` wins if given; otherwise ``COMPANY_BRAIN_LLM_PROVIDER`` env, then the
    ``default_provider`` in ``config/models.yaml``. The model id can be overridden
    for any provider with ``COMPANY_BRAIN_LLM_MODEL``.
    """
    cfg = load_models_config()
    key = (name or resolve_llm_provider()).strip().lower()
    spec = cfg.providers.get(key)
    if spec is None:
        known = ", ".join(sorted(cfg.providers)) or "(none configured)"
        raise ValueError(
            f"Unknown LLM provider '{key}'. Declare it in config/models.yaml "
            f"under `providers` (known: {known})."
        )

    model = os.getenv("COMPANY_BRAIN_LLM_MODEL", "").strip() or spec.model or None
    base_url = (os.getenv(_BASE_URL_ENV.get(key, ""), "") or "").strip() or None
    api_key = (os.getenv(_API_KEY_ENV.get(key, ""), "") or "").strip() or None

    # An OpenAI-compatible open-source provider must know where its server lives.
    if spec.sdk == "openai" and key == "glm" and not base_url:
        raise ValueError(
            "LLM provider 'glm' is selected but GLM_BASE_URL is not set. Point it "
            "at your OpenAI-compatible GLM-5 server — self-hosted on the cloud GPU "
            "VM, or a remote open-source host. Locally installing GLM-5 is not "
            "realistic; for local installs use the 'anthropic' or 'openai' provider."
        )

    return LLMProvider(key=key, sdk=spec.sdk, model=model, base_url=base_url, api_key=api_key)


def prompt_caching_1h_enabled() -> bool:
    """Whether to extend the Claude prompt-cache write TTL to 1 hour.

    Recurring agents make several LLM calls within a single run (e.g. absorb's
    per-batch loop, the verify/rework loop) against an unchanging system prompt.
    A 1h write TTL keeps those intra-run calls cache-hits even when spaced minutes
    apart. Controlled by ``ENABLE_PROMPT_CACHING_1H`` (read natively by the Claude
    Agent SDK; surfaced here so other layers can reason about it).
    """
    return os.getenv("ENABLE_PROMPT_CACHING_1H", "").strip().lower() in ("1", "true", "yes")
