"""Admin Manager — monthly LLM ops + investor newsletter dispatch.

Dispatches ``llm_expense_report`` then ``admin_maintain`` on the llm_ops cadence,
and ``investor_newsletter`` on its own run_day offset.
SDK: Neither (orchestration only).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from company_brain.agents.admin.admin_maintain import AdminMaintainAgent
from company_brain.agents.admin.investor_newsletter import InvestorNewsletterAgent
from company_brain.agents.admin.llm_expense_report import LlmExpenseReportAgent
from company_brain.agents.admin.llm_ops_config import (
    llm_ops_config,
    load_operations_raw,
    parse_hhmm,
    previous_month,
)
from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.llm.run_context import ambient_scope, new_run_id
from company_brain.runtime import get_runtime


def _investor_cfg() -> dict[str, Any]:
    raw = (load_operations_raw().get("admin") or {}).get("investor_newsletter") or {}
    return {
        "run_day": int(raw.get("run_day") or 3),
        "time": str(raw.get("time") or "09:00"),
    }


class AdminManager(BaseAgent):
    """Persistent manager for monthly LLM ops + investor newsletter."""

    name = "admin_manager"
    track_duration = False
    fleet_exempt = True

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
        from company_brain.admin_console.heartbeats import record_heartbeat
        from company_brain.runtime.fleet_gate import (
            can_dispatch,
            manager_heartbeat_detail,
            try_enter_paused,
        )

        self.logger.info("Admin manager starting persistent monthly loop")
        while True:
            try_enter_paused()
            record_heartbeat(self.name, detail=manager_heartbeat_detail())
            now = datetime.now()
            nxt = self._next_run_time(now)
            inv_nxt = self._next_investor_time(now)
            ups_nxt = self._next_upstream_time(now)
            wait = max(
                min(
                    (nxt - now).total_seconds(),
                    (inv_nxt - now).total_seconds(),
                    (ups_nxt - now).total_seconds(),
                ),
                30,
            )
            chunk = min(wait, 300)
            self.logger.info(
                "Next admin LLM-ops %s / investor %s / upstream %s (sleep %.0fs)",
                nxt.isoformat(),
                inv_nxt.isoformat(),
                ups_nxt.isoformat(),
                wait,
            )
            await asyncio.sleep(chunk)
            now = datetime.now()
            if not can_dispatch():
                try_enter_paused()
                continue
            if now >= nxt:
                try:
                    self.run_once(month=previous_month(), sync=True)
                except Exception:
                    self.logger.exception("Admin monthly LLM-ops run failed")
            if now >= inv_nxt:
                try:
                    self._run_investor(month=previous_month(), sync=True)
                except Exception:
                    self.logger.exception("Admin investor newsletter run failed")
            if now >= ups_nxt:
                try:
                    self._run_upstream_sync()
                except Exception:
                    self.logger.exception("Admin upstream sync run failed")

    def run_once(self, *, month: str | None = None, sync: bool = True) -> dict[str, Any]:
        from company_brain.admin_console.heartbeats import record_dispatch, record_heartbeat
        from company_brain.runtime.fleet_gate import dispatch_slot

        month = month or previous_month()
        record_heartbeat(self.name, detail=f"run_once:{month}")
        with dispatch_slot(self.name) as allowed:
            if not allowed:
                return {"month": month, "status": "skipped", "reason": "fleet_paused"}
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
            record_dispatch(self.name, result_status="ok")
            return {"month": month, "expense": expense, "maintain": maintain}

    def _run_investor(self, *, month: str, sync: bool = True) -> dict[str, Any]:
        from company_brain.runtime.fleet_gate import dispatch_slot

        store = StateStore()
        key = f"admin_manager:investor_newsletter:{month}"
        if store.get(key):
            return {"status": "skipped", "month": month, "reason": "already_ran"}
        with dispatch_slot(self.name) as allowed:
            if not allowed:
                return {"status": "skipped", "month": month, "reason": "fleet_paused"}
            runtime = get_runtime()
            with ambient_scope(
                manager=self.name,
                run_id=new_run_id(),
                reason="investor_newsletter",
            ):
                result = runtime.run(
                    InvestorNewsletterAgent,
                    self.config,
                    month=month,
                    sync=sync,
                )
            store.set(key, {"at": datetime.now().isoformat(), "result": str(result)[:200]})
            return {"status": "ok", "month": month, "investor": result}

    def _run_upstream_sync(self, *, force: bool = False) -> dict[str, Any]:
        from company_brain.agents.admin.upstream_sync import UpstreamSyncAgent
        from company_brain.runtime.fleet_gate import dispatch_slot

        with dispatch_slot(self.name) as allowed:
            if not allowed:
                return {"status": "skipped", "reason": "fleet_paused"}
            runtime = get_runtime()
            with ambient_scope(
                manager=self.name,
                run_id=new_run_id(),
                reason="upstream_sync",
            ):
                result = runtime.run(UpstreamSyncAgent, self.config, force=force)
            return {"status": "ok", "upstream_sync": result}

    def _next_upstream_time(self, now: datetime) -> datetime:
        from company_brain.agents.admin.upstream_sync import upstream_sync_config

        cfg = upstream_sync_config()
        day = int(cfg.get("day") or 15)
        target_t = parse_hhmm(str(cfg.get("time") or "10:00"))
        try:
            candidate = now.replace(
                day=day,
                hour=target_t.hour,
                minute=target_t.minute,
                second=0,
                microsecond=0,
            )
        except ValueError:
            nxt_month = (now.replace(day=28) + timedelta(days=4)).replace(day=1)
            last = nxt_month - timedelta(days=1)
            candidate = last.replace(
                hour=target_t.hour,
                minute=target_t.minute,
                second=0,
                microsecond=0,
            )
        if now >= candidate:
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

    def _next_investor_time(self, now: datetime) -> datetime:
        cfg = _investor_cfg()
        day = int(cfg.get("run_day") or 3)
        target_t = parse_hhmm(str(cfg.get("time") or "09:00"))
        try:
            candidate = now.replace(
                day=day,
                hour=target_t.hour,
                minute=target_t.minute,
                second=0,
                microsecond=0,
            )
        except ValueError:
            nxt_month = (now.replace(day=28) + timedelta(days=4)).replace(day=1)
            last = nxt_month - timedelta(days=1)
            candidate = last.replace(
                hour=target_t.hour,
                minute=target_t.minute,
                second=0,
                microsecond=0,
            )
        if now >= candidate:
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
