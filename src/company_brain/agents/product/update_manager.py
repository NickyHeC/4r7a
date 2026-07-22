"""Update manager — monthly customer product newsletter draft.

SDK: Neither (orchestration only). Never sends email.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.product.shared.workstream_config import (
    update_poll_minutes,
    update_run_day,
)

MONTH_KEY = "update_manager:month"


class UpdateManager(BaseAgent):
    """Persistent manager for the product update workstream."""

    name = "update_manager"
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

        interval = update_poll_minutes() * 60
        self.logger.info("Update manager starting (poll=%ss)", interval)
        while True:
            record_heartbeat(self.name, detail="idle")
            try:
                self.run_once()
            except Exception:
                self.logger.exception("Update manager pass failed")
            await asyncio.sleep(interval)

    def run_once(self, *, force: bool = False, **kwargs: Any) -> dict[str, Any]:
        from company_brain.admin_console.heartbeats import record_dispatch, record_heartbeat
        from company_brain.agents.product.update.product_update import ProductUpdateAgent
        from company_brain.runtime import get_runtime

        record_heartbeat(self.name, detail="run_once")
        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        if not force:
            if now.day < update_run_day():
                record_dispatch(self.name, result_status="skipped")
                return {"status": "skipped", "reason": "before_run_day", "month": month}
            if self._state.get(MONTH_KEY) == month:
                record_dispatch(self.name, result_status="skipped")
                return {"status": "skipped", "month": month}

        result = get_runtime().run(ProductUpdateAgent, self.config, force=force)
        self._state.set(MONTH_KEY, month)
        record_dispatch(self.name, result_status="ok")
        return {"status": "ok", "month": month, "product_update": result}
