"""SDK hooks that record LLM usage after each call."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from company_brain.llm.budget import record_usage
from company_brain.llm.run_budget import get_run_budget
from company_brain.llm.tiers import resolve_agent_model


def record_from_openai_result(
    agent_name: str,
    result: Any,
    *,
    model: str | None = None,
) -> None:
    """Record usage from an OpenAI Agents SDK ``RunResult``."""
    ctx = get_run_budget()
    if ctx is not None:
        ctx.begin_llm_step()

    usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
    if usage is None:
        return
    model_id = model or resolve_agent_model(agent_name).model_id
    record_usage(
        agent=agent_name,
        model=model_id,
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )
    if ctx is not None:
        requests = int(getattr(usage, "requests", 0) or 0)
        if requests:
            ctx.set_tool_calls(requests)


def _tokens_from_claude_usage(usage: dict[str, Any] | None) -> tuple[int, int]:
    if not usage:
        return 0, 0
    inp = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    out = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    return int(inp or 0), int(out or 0)


def record_from_claude_result(
    agent_name: str,
    message: Any,
    *,
    model: str | None = None,
) -> None:
    """Record usage from a Claude Agent SDK ``ResultMessage``."""
    from claude_agent_sdk import ResultMessage

    if not isinstance(message, ResultMessage):
        return
    ctx = get_run_budget()
    if ctx is not None:
        ctx.begin_llm_step()
    model_id = model or resolve_agent_model(agent_name).model_id
    inp, out = _tokens_from_claude_usage(message.usage)
    usd_val = message.total_cost_usd
    usd = float(usd_val) if usd_val is not None and float(usd_val) > 0 else None
    record_usage(
        agent=agent_name,
        model=model_id,
        input_tokens=inp,
        output_tokens=out,
        usd=usd,
    )
    if ctx is not None and message.num_turns:
        ctx.set_tool_calls(max(ctx.tool_calls, int(message.num_turns)))


async def iter_claude_query(
    agent_name: str,
    *,
    prompt: str,
    options: Any,
) -> AsyncIterator[Any]:
    """Wrap ``claude_agent_sdk.query`` and record usage from ``ResultMessage``."""
    from claude_agent_sdk import query

    async for message in query(prompt=prompt, options=options):
        record_from_claude_result(agent_name, message)
        yield message


def run_openai_sync(
    agent_name: str,
    agent: Any,
    prompt: str,
    *,
    run_config: Any = None,
    **kwargs: Any,
) -> Any:
    """Run OpenAI Agents SDK ``Runner.run_sync`` and record usage."""
    from agents import Runner

    result = Runner.run_sync(agent, prompt, run_config=run_config, **kwargs)
    record_from_openai_result(agent_name, result)
    return result
