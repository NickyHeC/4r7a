"""Helpers for OpenAI-Agents-SDK specialists to bind to the configured provider.

The OpenAI Agents SDK is the provider-flexible path: the same agent code runs on
OpenAI, Anthropic (via LiteLLM), or a self-hosted/remote open-source GLM-5 server
(OpenAI-compatible endpoint) by switching ``COMPANY_BRAIN_LLM_PROVIDER`` — no
external tokens are billed for the GLM path.

Build an agent like::

    from agents import Agent, Runner
    from company_brain.llm import openai_agents as oa

    agent = Agent(name="specialist", instructions="...", tools=[...],
                  model=oa.make_model())
    result = await Runner.run(agent, "...", run_config=oa.make_run_config())

All imports of the OpenAI Agents SDK are lazy so the package only needs to be
installed when an OpenAI-SDK agent actually runs.
"""

from __future__ import annotations

from typing import Any

from company_brain.llm.provider import LLMProvider, resolve_provider


def make_model(provider: LLMProvider | None = None) -> Any:
    """Return an OpenAI Agents SDK ``Model`` bound to the active provider.

    * ``anthropic`` -> ``LitellmModel("anthropic/<model>")`` (provider-agnostic
      access to Claude through the SDK's LiteLLM extension).
    * ``openai`` / ``glm`` (and any OpenAI-compatible endpoint) ->
      ``OpenAIChatCompletionsModel`` over an ``AsyncOpenAI`` client pointed at the
      provider's ``base_url``.
    """
    p = provider or resolve_provider()

    if p.key == "anthropic" or p.sdk == "claude":
        from agents.extensions.models.litellm_model import LitellmModel

        return LitellmModel(model=f"anthropic/{p.model}" if p.model else "anthropic/claude", api_key=p.api_key)

    from agents import OpenAIChatCompletionsModel
    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url=p.base_url, api_key=p.api_key or "not-needed")
    return OpenAIChatCompletionsModel(model=p.model or "gpt-5.5", openai_client=client)


def make_run_config(provider: LLMProvider | None = None) -> Any:
    """Return a ``RunConfig`` bound to the active provider's model.

    Disables OpenAI platform tracing when running against a non-OpenAI endpoint
    (so an OpenAI key is not required just to export traces).
    """
    p = provider or resolve_provider()
    from agents import RunConfig, set_tracing_disabled

    if p.key != "openai":
        set_tracing_disabled(True)
    return RunConfig(model=make_model(p))
