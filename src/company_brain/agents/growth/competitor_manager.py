"""Competitor manager — monthly discover + watch.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.growth.shared.workstream_config import competitor_poll_minutes

MONTH_KEY = "competitor_manager:month"


class CompetitorManager(BaseAgent):
    """Persistent manager for the competitor workstream."""

    name = "competitor_manager"
    track_duration = False

    def __init__(self, config, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()

    def run(self, *, once: bool = False, **kwargs: Any) -> Any:
        if once:
            return self.run_once(**kwargs)
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        from company_brain.admin_console.heartbeats import record_heartbeat

        interval = competitor_poll_minutes() * 60
        self.logger.info("Competitor manager starting (poll=%ss)", interval)
        while True:
            record_heartbeat(self.name, detail="idle")
            try:
                self.run_once()
            except Exception:
                self.logger.exception("Competitor manager pass failed")
            await asyncio.sleep(interval)

    def run_once(self, *, force: bool = False, **kwargs: Any) -> dict[str, Any]:
        from company_brain.admin_console.heartbeats import record_dispatch, record_heartbeat
        from company_brain.agents.growth.competitor.discover import CompetitorDiscoverAgent
        from company_brain.agents.growth.competitor.watch import CompetitorWatchAgent
        from company_brain.runtime import get_runtime

        record_heartbeat(self.name, detail="run_once")
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        if not force and self._state.get(MONTH_KEY) == month:
            record_dispatch(self.name, result_status="skipped")
            return {"status": "skipped", "month": month}

        runtime = get_runtime()
        results = {
            "discover": runtime.run(CompetitorDiscoverAgent, self.config, force=force),
            "watch": runtime.run(CompetitorWatchAgent, self.config, force=force),
            "month": month,
            "status": "ok",
        }
        self._state.set(MONTH_KEY, month)
        record_dispatch(self.name, result_status="ok")
        return results
