"""Bridge Manager — poll ledger, dispatch materializer, schedule daily rollup.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.bridge.blocker_rollup import BlockerRollupAgent
from company_brain.agents.bridge.bridge_event_materializer import BridgeEventMaterializerAgent
from company_brain.bridge.config import load_bridge_config
from company_brain.bridge.events import BridgeEventStore
from company_brain.config import AppConfig
from company_brain.runtime import get_runtime


def _parse_rollup_time(raw: str) -> time:
    try:
        hour, minute = raw.strip().split(":", 1)
        return time(int(hour), int(minute))
    except (ValueError, TypeError):
        return time(8, 0)


class BridgeManagerAgent(BaseAgent):
    name = "bridge_manager"
    track_duration = False

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._events = BridgeEventStore()
        self._last_rollup_date: str | None = None

    def run(self, *, once: bool = False, **kwargs: Any) -> Any:
        if once:
            return self.run_once()
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        cfg = load_bridge_config()
        interval = max(1, cfg.poll_interval_minutes)
        self.logger.info("Bridge manager starting (poll every %d min)", interval)
        while True:
            try:
                self.run_once()
            except Exception:
                self.logger.exception("Bridge manager poll failed")
            await asyncio.sleep(max(interval * 60, 30))

    def run_once(self) -> dict[str, Any]:
        materialized = self._dispatch_materializers()
        rollup = self._maybe_run_rollup()
        return {"materialized": materialized, "rollup": rollup}

    def _dispatch_materializers(self) -> int:
        dispatched = 0
        for event in self._events.list_unmaterialized():
            try:
                result = get_runtime().run(
                    BridgeEventMaterializerAgent,
                    self.config,
                    event=event,
                )
                if result.get("status") == "ok" and not result.get("skipped"):
                    dispatched += 1
            except Exception:
                self.logger.exception("Bridge materializer failed for %s", event.event_id)
        return dispatched

    def _maybe_run_rollup(self) -> dict[str, Any] | None:
        cfg = load_bridge_config()
        target = _parse_rollup_time(cfg.rollup.time)
        now = datetime.now()
        today = now.date().isoformat()
        if self._last_rollup_date == today:
            return None
        if now.time() < target:
            return None
        try:
            result = get_runtime().run(BlockerRollupAgent, self.config)
            self._last_rollup_date = today
            return result
        except Exception:
            self.logger.exception("Blocker rollup failed")
            return {"status": "error"}
