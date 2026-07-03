"""Per-run budget enforcement (Layer B).

Caps are resolved from ``config/models.yaml`` ``run_limits`` and enforced outside
the model — before each execute iteration and before/after each LLM SDK call.
Agents never see counters in prompts (Ramp Labs finding).
"""

from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass, field
from typing import Iterator

from company_brain.config import RunLimitValues
from company_brain.llm.budget import resolve_run_limits
from company_brain.llm.tiers import resolve_llm_agent_key

_current: contextvars.ContextVar[RunBudget | None] = contextvars.ContextVar(
    "run_budget",
    default=None,
)


class RunLimitExceededError(RuntimeError):
    """Raised when a per-run cap (USD, steps, or tool calls) is exceeded."""


@dataclass
class RunBudget:
    """Tracks spend for one agent execution."""

    agent: str
    llm_key: str
    limits: RunLimitValues
    spent_usd: float = 0.0
    steps: int = 0
    tool_calls: int = 0
    _llm_steps: int = field(default=0, repr=False)

    def _check(self, *, reason: str, detail: str) -> None:
        limits = self.limits
        if limits.max_steps_per_run is not None and self.steps >= limits.max_steps_per_run:
            raise RunLimitExceededError(
                f"Run step limit exceeded for '{self.agent}' "
                f"({self.steps}/{limits.max_steps_per_run}): {detail} [{reason}]",
            )
        if limits.max_usd_per_run is not None and self.spent_usd > limits.max_usd_per_run:
            raise RunLimitExceededError(
                f"Run spend limit exceeded for '{self.agent}' "
                f"(${self.spent_usd:.4f}/${limits.max_usd_per_run:.2f}): {detail} [{reason}]",
            )
        if (
            limits.max_tool_calls_per_run is not None
            and self.tool_calls > limits.max_tool_calls_per_run
        ):
            raise RunLimitExceededError(
                f"Run tool-call limit exceeded for '{self.agent}' "
                f"({self.tool_calls}/{limits.max_tool_calls_per_run}): {detail} [{reason}]",
            )

    def begin_execute_step(self) -> None:
        """Count one ``run`` -> ``verify`` iteration in ``BaseAgent.execute()``."""
        self._check(reason="max_steps_per_run", detail="execute iteration")
        self.steps += 1

    def begin_llm_step(self) -> None:
        """Count one nested LLM SDK invocation (may happen inside a single ``run()``)."""
        self._check(reason="max_steps_per_run", detail="LLM call")
        self._llm_steps += 1
        self.steps += 1

    def add_cost(self, usd: float) -> None:
        if usd <= 0:
            return
        self.spent_usd += usd
        self._check(reason="max_usd_per_run", detail="LLM usage recorded")

    def set_tool_calls(self, total: int) -> None:
        """Set cumulative tool-call count from SDK usage (monotonic)."""
        if total <= self.tool_calls:
            return
        self.tool_calls = total
        self._check(reason="max_tool_calls_per_run", detail="SDK tool usage")

    def add_tool_calls(self, count: int = 1) -> None:
        if count <= 0:
            return
        self.tool_calls += count
        self._check(reason="max_tool_calls_per_run", detail="tool invocation")


def get_run_budget() -> RunBudget | None:
    return _current.get()


def agent_matches_run(ctx: RunBudget, agent: str) -> bool:
    return agent in {ctx.agent, ctx.llm_key}


def start_run_budget(agent: str) -> RunBudget:
    llm_key = resolve_llm_agent_key(agent) or agent
    limits = resolve_run_limits(agent)
    return RunBudget(agent=agent, llm_key=llm_key, limits=limits)


@contextlib.contextmanager
def run_budget_scope(agent: str) -> Iterator[RunBudget]:
    """Install a per-run budget for the duration of an agent execution."""
    budget = start_run_budget(agent)
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)
