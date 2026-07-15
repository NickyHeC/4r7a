"""SDK hooks that record LLM usage after each call."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from company_brain.llm.budget import record_usage
from company_brain.llm.run_budget import get_run_budget
from company_brain.llm.tiers import resolve_agent_model


def _int_attr(obj: Any, *names: str) -> int:
    for name in names:
        if isinstance(obj, dict):
            val = obj.get(name)
        else:
            val = getattr(obj, name, None)
        if val is not None:
            return int(val or 0)
    return 0


def _dims_from_usage(usage: Any) -> dict[str, int]:
    """Extract token dimensions from OpenAI- or Claude-shaped usage objects."""
    if usage is None:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
        }
    inp = _int_attr(usage, "input_tokens", "prompt_tokens")
    out = _int_attr(usage, "output_tokens", "completion_tokens")
    cache_read = _int_attr(
        usage,
        "cache_read_input_tokens",
        "cache_read_tokens",
        "cached_tokens",
    )
    cache_write = _int_attr(
        usage,
        "cache_creation_input_tokens",
        "cache_write_tokens",
        "cache_creation_tokens",
    )
    reasoning = _int_attr(usage, "reasoning_tokens", "output_reasoning_tokens")
    details = None
    if isinstance(usage, dict):
        details = usage.get("output_tokens_details") or usage.get("completion_tokens_details")
    else:
        details = getattr(usage, "output_tokens_details", None) or getattr(
            usage, "completion_tokens_details", None
        )
    if details is not None and reasoning == 0:
        reasoning = _int_attr(details, "reasoning_tokens")
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "reasoning_tokens": reasoning,
    }


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
    dims = _dims_from_usage(usage)
    record_usage(agent=agent_name, model=model_id, **dims)
    if ctx is not None:
        requests = int(getattr(usage, "requests", 0) or 0)
        if requests:
            ctx.set_tool_calls(requests)


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
    dims = _dims_from_usage(message.usage)
    usd_val = message.total_cost_usd
    usd = float(usd_val) if usd_val is not None and float(usd_val) > 0 else None
    record_usage(agent=agent_name, model=model_id, usd=usd, **dims)
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
