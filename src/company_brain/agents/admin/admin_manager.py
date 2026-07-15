"""Admin Manager — monthly LLM ops maintenance period.

Dispatches ``llm_expense_report`` then ``admin_maintain`` on a shared cadence.
SDK: Neither (orchestration only).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from company_brain.agents.admin.admin_maintain import AdminMaintainAgent
from company_brain.agents.admin.llm_expense_report import LlmExpenseReportAgent
from company_brain.agents.admin.llm_ops_config import llm_ops_config, parse_hhmm, previous_month
from company_brain.agents.base import BaseAgent
from company_brain.llm.run_context import ambient_scope, new_run_id
from company_brain.runtime import get_runtime


class AdminManager(BaseAgent):
    """Persistent manager for the monthly LLM expense + maintain pair."""

    name = "admin_manager"
    track_duration = False

    def run(
        self,
        *,
        once: bool = False,
        month: str | None = None,
        sync: bool = True,
        **kwargs: Any,
    ) -> Any:
        if once:
            return self.run_once(month=month, sync=sync)
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        self.logger.info("Admin manager starting persistent monthly loop")
        while True:
            now = datetime.now()
            nxt = self._next_run_time(now)
            wait = max((nxt - now).total_seconds(), 30)
            self.logger.info("Next admin LLM-ops run at %s (sleep %.0fs)", nxt.isoformat(), wait)
            await asyncio.sleep(wait)
            try:
                self.run_once(month=previous_month(), sync=True)
            except Exception:
                self.logger.exception("Admin monthly LLM-ops run failed")

    def run_once(self, *, month: str | None = None, sync: bool = True) -> dict[str, Any]:
        month = month or previous_month()
        runtime = get_runtime()
        with ambient_scope(
            manager=self.name,
            run_id=new_run_id(),
            reason="monthly_llm_ops",
        ):
            expense = runtime.run(
                LlmExpenseReportAgent,
                self.config,
                month=month,
                sync=sync,
            )
            maintain = runtime.run(
                AdminMaintainAgent,
                self.config,
                month=month,
                sync=sync,
            )
        return {"month": month, "expense": expense, "maintain": maintain}

    def _next_run_time(self, now: datetime) -> datetime:
        cfg = llm_ops_config()
        day = int(cfg.get("day") or 1)
        target_t = parse_hhmm(str(cfg.get("time") or "09:00"))
        candidate = now.replace(
            day=min(day, 28),
            hour=target_t.hour,
            minute=target_t.minute,
            second=0,
            microsecond=0,
        )
        # Clamp to actual month length
        try:
            candidate = now.replace(
                day=day,
                hour=target_t.hour,
                minute=target_t.minute,
                second=0,
                microsecond=0,
            )
        except ValueError:
            # day out of range for this month — use last day
            nxt_month = (now.replace(day=28) + timedelta(days=4)).replace(day=1)
            last = nxt_month - timedelta(days=1)
            candidate = last.replace(
                hour=target_t.hour,
                minute=target_t.minute,
                second=0,
                microsecond=0,
            )
        if now >= candidate:
            # jump to next month
            year = candidate.year + (1 if candidate.month == 12 else 0)
            month = 1 if candidate.month == 12 else candidate.month + 1
            try:
                candidate = candidate.replace(year=year, month=month, day=day)
            except ValueError:
                nxt = datetime(year, month, 28) + timedelta(days=4)
                last = nxt.replace(day=1) - timedelta(days=1)
                candidate = last.replace(
                    hour=target_t.hour,
                    minute=target_t.minute,
                    second=0,
                    microsecond=0,
                )
        return candidate
