"""Lead manager — drains pending research jobs from the wiki queue.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

import asyncio
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.leads.queue import list_pending_jobs
from company_brain.agents.growth.shared.workstream_config import leads_poll_minutes


class LeadManager(BaseAgent):
    """Persistent manager for the lead research workstream."""

    name = "lead_manager"
    track_duration = False

    def run(self, *, once: bool = False, **kwargs: Any) -> Any:
        if once:
            return self.run_once(**kwargs)
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        from company_brain.admin_console.heartbeats import record_heartbeat

        interval = leads_poll_minutes() * 60
        self.logger.info("Lead manager starting (poll=%ss)", interval)
        while True:
            record_heartbeat(self.name, detail="idle")
            try:
                self.run_once()
            except Exception:
                self.logger.exception("Lead manager pass failed")
            await asyncio.sleep(interval)

    def run_once(self, **kwargs: Any) -> dict[str, Any]:
        from company_brain.admin_console.heartbeats import record_dispatch, record_heartbeat
        from company_brain.agents.growth.leads.lead_research import LeadResearchAgent
        from company_brain.runtime import get_runtime

        record_heartbeat(self.name, detail="run_once")
        jobs = list_pending_jobs()
        if not jobs:
            record_dispatch(self.name, result_status="skipped")
            return {"status": "skipped", "reason": "empty_queue"}

        runtime = get_runtime()
        results = []
        for job in jobs:
            results.append(runtime.run(LeadResearchAgent, self.config, job=job))
        record_dispatch(self.name, result_status="ok")
        return {"status": "ok", "jobs": len(results), "results": results}
