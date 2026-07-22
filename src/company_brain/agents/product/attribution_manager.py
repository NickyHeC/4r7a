"""Attribution manager — activity ↔ signup spike matching.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

import asyncio
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import changed_since
from company_brain.agents.product.shared.workstream_config import attribution_poll_minutes


class AttributionManager(BaseAgent):
    """Persistent manager for the attribution workstream."""

    name = "attribution_manager"
    track_duration = False

    def run(self, *, once: bool = False, **kwargs: Any) -> Any:
        if once:
            return self.run_once(**kwargs)
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        from company_brain.admin_console.heartbeats import record_heartbeat

        interval = attribution_poll_minutes() * 60
        self.logger.info("Attribution manager starting (poll=%ss)", interval)
        while True:
            record_heartbeat(self.name, detail="idle")
            try:
                self.run_once()
            except Exception:
                self.logger.exception("Attribution manager pass failed")
            await asyncio.sleep(interval)

    def run_once(self, *, force: bool = False, **kwargs: Any) -> dict[str, Any]:
        from company_brain.admin_console.heartbeats import record_dispatch, record_heartbeat
        from company_brain.agents.product.attribution.signup_match import (
            SignupMatchAgent,
            activity_signup_signature,
        )
        from company_brain.runtime import get_runtime

        record_heartbeat(self.name, detail="run_once")
        signature = activity_signup_signature()
        if not force and not changed_since(
            "attribution_manager:signature", signature, update=False
        ):
            record_dispatch(self.name, result_status="skipped")
            return {"status": "skipped", "reason": "unchanged"}

        result = get_runtime().run(SignupMatchAgent, self.config, force=force)
        changed_since("attribution_manager:signature", signature, update=True)
        record_dispatch(self.name, result_status="ok")
        return {"status": "ok", "signup_match": result}
