"""Content manager — drafts cadence, weekly published pull, schedule refresh.

SDK: Neither (orchestration only). Never posts to social platforms.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.growth.shared.workstream_config import (
    content_poll_minutes,
    content_weekly_pull_weekday,
)

WEEK_KEY = "content_manager:weekly_pull"


class ContentManager(BaseAgent):
    """Persistent manager for the content workstream."""

    name = "content_manager"
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

        interval = content_poll_minutes() * 60
        self.logger.info("Content manager starting (poll=%ss)", interval)
        while True:
            record_heartbeat(self.name, detail="idle")
            try:
                self.run_once()
            except Exception:
                self.logger.exception("Content manager pass failed")
            await asyncio.sleep(interval)

    def run_once(
        self, *, items: list[dict[str, str]] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        from company_brain.admin_console.heartbeats import record_dispatch, record_heartbeat
        from company_brain.agents.growth.content.posting_schedule import PostingScheduleAgent
        from company_brain.agents.growth.content.published_pull import PublishedPullAgent
        from company_brain.runtime import get_runtime

        record_heartbeat(self.name, detail="run_once")
        runtime = get_runtime()
        out: dict[str, Any] = {"status": "ok"}
        out["posting_schedule"] = runtime.run(PostingScheduleAgent, self.config)

        now = datetime.now(timezone.utc)
        week = now.strftime("%G-W%V")
        weekday = content_weekly_pull_weekday()
        if items is not None or (now.weekday() == weekday and self._state.get(WEEK_KEY) != week):
            out["published_pull"] = runtime.run(
                PublishedPullAgent,
                self.config,
                items=items or [],
                force=bool(items),
            )
            self._state.set(WEEK_KEY, week)

        record_dispatch(self.name, result_status="ok")
        return out
