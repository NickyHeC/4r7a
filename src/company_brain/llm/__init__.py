"""LLM provider abstraction.

One knob (``COMPANY_BRAIN_LLM_PROVIDER`` + ``config/models.yaml``) switches the
model behind every agent across the two agent SDKs the project uses:

* Claude Agent SDK agents resolve their model via ``llm.claude``.
* OpenAI Agents SDK specialists bind to the provider via ``llm.openai_agents``
  (this is the provider-flexible path that can target a self-hosted/remote
  open-source GLM-5 endpoint at no external token cost).
"""

from company_brain.llm.provider import (
    LLMProvider,
    prompt_caching_1h_enabled,
    resolve_provider,
)

__all__ = [
    "LLMProvider",
    "resolve_provider",
    "prompt_caching_1h_enabled",
]
