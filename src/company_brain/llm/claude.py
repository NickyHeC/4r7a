"""Helpers for Claude-Agent-SDK agents to pick up the configured provider.

Claude-SDK agents (the absorb writer and the MCP-native / big-context reasoning
agents) keep using ``claude_agent_sdk.query`` directly. These helpers let them
resolve their model from ``config/models.yaml`` instead of hardcoding one, and
keep prompt caching working.

Imports stay lazy at the call sites: nothing here imports ``claude_agent_sdk``,
so agents preserve their deterministic fallback when the SDK is not installed.

Note on running Claude-SDK agents on open-source models: the Claude Agent SDK
reads ``ANTHROPIC_BASE_URL``/``ANTHROPIC_API_KEY`` from the environment itself, so
pointing it at a LiteLLM gateway that exposes an Anthropic-compatible endpoint
backed by GLM-5 is a deployment/env concern (set those vars) rather than a code
change. The clean open-source path is the OpenAI Agents SDK (``llm.openai_agents``).
"""

from __future__ import annotations

from company_brain.llm.provider import LLMProvider, prompt_caching_1h_enabled, resolve_provider


def model_kwargs(
    explicit: str | None = None,
    provider: LLMProvider | None = None,
    *,
    agent_name: str | None = None,
) -> dict[str, str]:
    """``{"model": ...}`` to splat into ``ClaudeAgentOptions`` (empty -> SDK default).

    An ``explicit`` model (e.g. a CLI ``--model`` override) wins. With
    ``agent_name``, resolves the per-agent tier from ``config/models.yaml``.
    """
    if explicit:
        return {"model": explicit}
    if agent_name:
        from company_brain.llm.budget import check_budget
        from company_brain.llm.tiers import resolve_agent_model

        check_budget(agent=agent_name)
        binding = resolve_agent_model(agent_name)
        return {"model": binding.model_id}
    p = provider or resolve_provider()
    if p.sdk == "claude" and p.model:
        return {"model": p.model}
    return {}


def options_env(provider: LLMProvider | None = None) -> dict[str, str]:
    """Environment overrides to pass via ``ClaudeAgentOptions(env=...)``.

    Enables the 1h prompt-cache TTL when configured. Returns an empty dict when
    there is nothing to override (callers can splat it unconditionally).
    """
    env: dict[str, str] = {}
    if prompt_caching_1h_enabled():
        env["ENABLE_PROMPT_CACHING_1H"] = "1"
    return env
