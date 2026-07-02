"""Linear Manager Agent — persistent poll for terminal issues and dispatch completion.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.linear import linear_client
from company_brain.agents.engineering.linear.task_bindings import TaskBindingStore
from company_brain.agents.engineering.shared.linear_config import (
    poll_interval_minutes,
    stale_audit_cfg,
    team_id,
    team_key,
)
from company_brain.agents.gates import StateStore, is_handled, mark_handled
from company_brain.config import AppConfig

POLL_STATE_KEY = "linear_manager:last_poll"
STALE_HANDLED_PREFIX = "linear_stale_audit:"


class LinearManagerAgent(BaseAgent):
    """Poll Linear for recently updated terminal issues and dispatch completion handlers."""

    name = "linear_manager"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()
        self._bindings = TaskBindingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return linear_client.linear_is_configured()

    def run(self, *, once: bool = False, **kwargs: Any) -> Any:
        if once:
            return self.run_once()
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        interval = poll_interval_minutes()
        self.logger.info("Linear manager starting (poll every %d min)", interval)
        while True:
            try:
                self.run_once()
            except Exception:
                self.logger.exception("Linear manager poll failed")
            await asyncio.sleep(max(interval * 60, 60))

    def run_once(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        since = self._since_timestamp(now)
        issues = linear_client.list_issues_updated_since(
            since,
            team_id=team_id() or None,
            team_key=team_key() or None,
            first=100,
        )
        dispatched = 0
        for issue in issues:
            if not linear_client.is_terminal_issue(issue):
                continue
            ref = issue.get("id") or issue.get("identifier") or ""
            signature = f"{ref}:{issue.get('updatedAt', '')}"
            if is_handled("linear_completed", signature, store=self._state):
                continue
            binding = self._bindings.find_by_linear(ref)
            if not binding:
                continue
            self._dispatch_completed(binding.task_id, issue)
            mark_handled("linear_completed", signature, store=self._state)
            dispatched += 1

        self._state.set(POLL_STATE_KEY, now.isoformat())
        stale = self._maybe_run_stale_audit(now)
        if dispatched:
            self.logger.info("Dispatched linear_completed for %d issue(s)", dispatched)
        return {"polled": len(issues), "dispatched": dispatched, "stale_audit": stale}

    def _maybe_run_stale_audit(self, now: datetime) -> dict[str, Any] | None:
        from company_brain.agents.scheduling.work_ahead import should_run_work_ahead

        cfg = stale_audit_cfg()
        ready = cfg.get("ready_for") or {}
        ready_day = str(ready.get("day") or cfg.get("day") or "monday")
        ready_time = str(ready.get("time") or cfg.get("time") or "09:00")
        estimated = int(cfg.get("estimated_minutes") or 15)
        buffer = int(cfg.get("buffer_minutes") or 45)

        if not should_run_work_ahead(
            ready_day=ready_day,
            ready_time=ready_time,
            estimated_minutes=estimated,
            buffer_minutes=buffer,
            now=now,
        ):
            return None

        week_key = f"{STALE_HANDLED_PREFIX}{now.strftime('%G-W%V')}"
        if is_handled("linear_stale_audit", week_key, store=self._state):
            return None
        from company_brain.agents.engineering.linear.stale_audit import StaleAuditAgent
        from company_brain.runtime import get_runtime

        mark_handled("linear_stale_audit", week_key, store=self._state)
        return get_runtime().run(
            StaleAuditAgent,
            self.config,
            dispatch_manual=True,
            wait_for_completion=False,
        )

    def _since_timestamp(self, now: datetime) -> datetime:
        raw = self._state.get(POLL_STATE_KEY)
        if raw:
            try:
                return datetime.fromisoformat(str(raw))
            except ValueError:
                pass
        return now - timedelta(minutes=poll_interval_minutes())

    def _dispatch_completed(self, task_id: str, issue: dict[str, Any]) -> None:
        from company_brain.agents.engineering.linear.linear_completed import LinearCompletedAgent
        from company_brain.runtime import get_runtime

        get_runtime().run(
            LinearCompletedAgent,
            self.config,
            task_id=task_id,
            linear_issue=issue,
        )
