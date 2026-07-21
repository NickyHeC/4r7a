"""Activity manager — persistent dispatcher for company event lifecycle.

Polls registered events and advances planning / wrap when status markers say so.
Registration itself is human-gated (CLI / console / @wiki), not invented here.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

import asyncio
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.growth.activity.event_paths import EVENT_DIR
from company_brain.agents.growth.shared.workstream_config import activity_poll_minutes
from company_brain.wiki.store import LocalWikiStore

PLAN_QUEUE_KEY = "activity_manager:plan_queue"


class ActivityManager(BaseAgent):
    """Persistent manager for the company activity workstream."""

    name = "activity_manager"
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

        interval = activity_poll_minutes() * 60
        self.logger.info("Activity manager starting (poll=%ss)", interval)
        while True:
            record_heartbeat(self.name, detail="idle")
            try:
                self.run_once()
            except Exception:
                self.logger.exception("Activity manager pass failed")
            await asyncio.sleep(interval)

    def run_once(self, **kwargs: Any) -> dict[str, Any]:
        from company_brain.admin_console.heartbeats import record_dispatch, record_heartbeat
        from company_brain.agents.growth.activity.event_plan import EventPlanAgent
        from company_brain.runtime import get_runtime

        record_heartbeat(self.name, detail="run_once")
        runtime = get_runtime()
        planned: list[str] = []
        store = LocalWikiStore()
        for rel in store.list(EVENT_DIR + "/"):
            if not rel.endswith(".md") or "-partner-" in rel:
                continue
            doc = store.read(rel)
            status = str(doc.frontmatter.get("event_status") or "")
            default_slug = rel.rsplit("/", 1)[-1].removesuffix(".md")
            slug = str(doc.frontmatter.get("event_slug") or default_slug)
            if status == "registered":
                runtime.run(EventPlanAgent, self.config, slug=slug)
                planned.append(slug)
        record_dispatch(self.name, result_status="ok")
        return {"status": "ok", "planned": planned}
