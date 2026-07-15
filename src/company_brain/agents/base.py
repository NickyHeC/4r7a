"""Base agent class: lifecycle, eval loop, cost gate, logging, and config."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from contextlib import nullcontext
from typing import Any

from company_brain.agents.result import AgentResult
from company_brain.config import AppConfig
from company_brain.llm.run_budget import RunLimitExceededError, run_budget_scope

logger = logging.getLogger(__name__)

# Sentinel returned by execute() when the cost gate skips a run.
SKIPPED = object()


class BaseAgent(ABC):
    """Base class for company-brain agents.

    Agents are long-lived processes or triggered tasks that perform specific
    wiki maintenance operations (ingestion, cleanup, sync, etc.).

    The lifecycle is: ``should_run`` (cheap cost gate) -> ``setup`` ->
    [ ``run`` -> ``verify`` ] looped up to ``max_iterations`` -> ``teardown``.
    Defaults make this a transparent one-shot, so existing agents are unchanged.
    """

    name: str = "base-agent"

    #: Raise in a subclass to opt into the rework loop (run -> verify -> retry).
    max_iterations: int = 1

    #: Wall-clock duration for ephemeral specialists (feeds work-ahead). Persistent
    #: managers set this False — they dispatch specialists; they are not timed.
    track_duration: bool = True

    def __init__(self, config: AppConfig, **kwargs: Any):
        self.config = config
        self.logger = logging.getLogger(f"company_brain.agents.{self.name}")

    @abstractmethod
    def run(self, **kwargs: Any) -> Any:
        """Execute the agent's primary task."""
        ...

    def should_run(self, **kwargs: Any) -> bool:
        """Cheap ($0) cost gate. Return False to skip the run entirely.

        Override in expensive (LLM) agents to skip when nothing changed since
        the last run. Default always runs.
        """
        return True

    def verify(self, output: Any, **kwargs: Any) -> AgentResult:
        """Check output against the agent's standard.

        Default trusts the output (status='ok'). Override to triage the result
        as 'ok' | 'rework' | 'noise' and to drive bounded iteration.
        """
        return AgentResult(output=output, status="ok")

    def setup(self) -> None:
        """Optional setup hook, called before run()."""
        pass

    def teardown(self) -> None:
        """Optional teardown hook, called after run()."""
        pass

    def execute(self, **kwargs: Any) -> Any:
        """Full agent lifecycle: cost gate -> setup -> run/verify loop -> teardown."""
        self.logger.info("Starting agent '%s'", self.name)
        if not self.should_run(**kwargs):
            self.logger.info("Agent '%s' skipped by cost gate (no change)", self.name)
            return SKIPPED

        session_id = kwargs.get("session_id")
        if session_id:
            from company_brain.llm.run_context import ambient_scope

            scope = ambient_scope(session_id=str(session_id))
        else:
            scope = nullcontext()

        started = time.monotonic() if self.track_duration else None
        final_status: str | None = None
        try:
            with scope:
                with run_budget_scope(self.name) as run_budget:
                    self.setup()
                    result: AgentResult | None = None
                    for attempt in range(1, self.max_iterations + 1):
                        run_budget.begin_execute_step()
                        output = self.run(**kwargs)
                        result = self.verify(output, **kwargs)
                        if result.passed:
                            break
                        self.logger.info(
                            "Agent '%s' attempt %d/%d: status=%s gaps=%s",
                            self.name,
                            attempt,
                            self.max_iterations,
                            result.status,
                            result.gaps,
                        )
                    final_status = result.status if result is not None else None
                    self.logger.info(
                        "Agent '%s' completed (status=%s)",
                        self.name,
                        final_status,
                    )
                    return result.output if result is not None else None
        except RunLimitExceededError:
            self.logger.error("Agent '%s' stopped by per-run budget cap", self.name)
            raise
        except Exception:
            self.logger.exception("Agent '%s' failed", self.name)
            raise
        finally:
            if final_status is not None:
                try:
                    from company_brain.llm.budget import record_verify_verdict

                    record_verify_verdict(self.name, final_status)
                except Exception:
                    self.logger.debug(
                        "Failed to record verify verdict for '%s'",
                        self.name,
                        exc_info=True,
                    )
            if started is not None:
                try:
                    from company_brain.llm.duration import record_execute_duration

                    record_execute_duration(
                        self.name,
                        (time.monotonic() - started) * 1000.0,
                    )
                except Exception:
                    self.logger.debug(
                        "Failed to record execute duration for '%s'",
                        self.name,
                        exc_info=True,
                    )
            self.teardown()
