"""Progress manager — weekly product progress compile.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.product.shared.workstream_config import progress_poll_minutes

WEEK_KEY = "progress_manager:week"


class ProgressManager(BaseAgent):
    """Persistent manager for the progress workstream."""

    name = "progress_manager"
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

        interval = progress_poll_minutes() * 60
        self.logger.info("Progress manager starting (poll=%ss)", interval)
        while True:
            record_heartbeat(self.name, detail="idle")
            try:
                self.run_once()
            except Exception:
                self.logger.exception("Progress manager pass failed")
            await asyncio.sleep(interval)

    def run_once(self, *, force: bool = False, **kwargs: Any) -> dict[str, Any]:
        from company_brain.admin_console.heartbeats import record_dispatch, record_heartbeat
        from company_brain.agents.product.progress.compile import ProgressCompileAgent
        from company_brain.runtime import get_runtime

        record_heartbeat(self.name, detail="run_once")
        week = datetime.now(timezone.utc).strftime("%G-W%V")
        if not force and self._state.get(WEEK_KEY) == week:
            record_dispatch(self.name, result_status="skipped")
            return {"status": "skipped", "week": week}

        result = get_runtime().run(ProgressCompileAgent, self.config, force=force)
        self._state.set(WEEK_KEY, week)
        record_dispatch(self.name, result_status="ok")
        return {"status": "ok", "week": week, "progress_compile": result}
