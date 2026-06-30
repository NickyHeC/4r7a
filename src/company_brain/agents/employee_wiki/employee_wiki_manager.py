"""Employee Wiki Manager — poll work_events ledger and dispatch materializers.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

import asyncio
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.employee_wiki.work_event_materializer import WorkEventMaterializerAgent
from company_brain.config import AppConfig, load_yaml_config
from company_brain.runtime import get_runtime
from company_brain.wiki.work_events import WorkEventStore

DEFAULT_POLL_MINUTES = 5


def poll_interval_minutes() -> int:
    block = load_yaml_config("operations").get("employee_wiki") or {}
    try:
        return max(1, int(block.get("poll_interval_minutes") or DEFAULT_POLL_MINUTES))
    except (TypeError, ValueError):
        return DEFAULT_POLL_MINUTES


class EmployeeWikiManagerAgent(BaseAgent):
    """Dispatch materializers for unprocessed work events."""

    name = "employee_wiki_manager"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._events = WorkEventStore()

    def run(self, *, once: bool = False, **kwargs: Any) -> Any:
        if once:
            return self.run_once()
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        interval = poll_interval_minutes()
        self.logger.info("Employee wiki manager starting (poll every %d min)", interval)
        while True:
            try:
                self.run_once()
            except Exception:
                self.logger.exception("Employee wiki manager poll failed")
            await asyncio.sleep(max(interval * 60, 30))

    def run_once(self) -> dict[str, Any]:
        pending = self._events.list_unmaterialized(target="employee")
        dispatched = 0
        results: list[dict[str, Any]] = []
        for event in pending:
            try:
                result = get_runtime().run(
                    WorkEventMaterializerAgent,
                    self.config,
                    event=event,
                )
                results.append(result)
                if result.get("status") == "ok":
                    dispatched += 1
            except Exception:
                self.logger.exception("Materializer failed for event %s", event.event_id)
        return {"pending": len(pending), "dispatched": dispatched, "results": results}
