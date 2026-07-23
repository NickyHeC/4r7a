"""Admin Manager — monthly LLM ops + scout / hygiene / upstream dispatch.

Dispatches ``llm_expense_report`` then ``admin_maintain`` on the llm_ops cadence,
``investor_newsletter``, ``upstream_sync``, ``process_scout``, ``wiki_ops_audit``,
and quarterly ``doc_hygiene``.
SDK: Neither (orchestration only).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from company_brain.agents.admin.admin_maintain import AdminMaintainAgent
from company_brain.agents.admin.investor_newsletter import InvestorNewsletterAgent
from company_brain.agents.admin.llm_expense_report import LlmExpenseReportAgent
from company_brain.agents.admin.llm_ops_config import (
    llm_ops_config,
    load_operations_raw,
    previous_month,
)
from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.scheduling.calendar import next_calendar_run, parse_hhmm
from company_brain.llm.run_context import ambient_scope, new_run_id
from company_brain.runtime import get_runtime


def _investor_cfg() -> dict[str, Any]:
    raw = (load_operations_raw().get("admin") or {}).get("investor_newsletter") or {}
    return {
        "run_day": int(raw.get("run_day") or 3),
        "time": str(raw.get("time") or "09:00"),
    }


def _next_day_of_month(now: datetime, *, day: int, time_str: str) -> datetime:
    """Next occurrence of day-of-month at HH:MM (clamps short months)."""
    return next_calendar_run(now, day=day, at=parse_hhmm(time_str))


class AdminManager(BaseAgent):
    """Persistent manager for monthly admin ops + scouts."""

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
            times = [
                self._next_run_time(now),
                self._next_investor_time(now),
                self._next_upstream_time(now),
                self._next_process_scout_time(now),
                self._next_wiki_ops_time(now),
                self._next_doc_hygiene_time(now),
            ]
            wait = max(min((t - now).total_seconds() for t in times), 30)
            chunk = min(wait, 300)
            self.logger.info(
                "Next admin schedules soonest in %.0fs (llm/investor/upstream/scout/wiki/docs)",
                wait,
            )
            await asyncio.sleep(chunk)
            now = datetime.now()
            if not can_dispatch():
                try_enter_paused()
                continue
            if now >= times[0]:
                try:
                    self.run_once(month=previous_month(), sync=True)
                except Exception:
                    self.logger.exception("Admin monthly LLM-ops run failed")
            if now >= times[1]:
                try:
                    self._run_investor(month=previous_month(), sync=True)
                except Exception:
                    self.logger.exception("Admin investor newsletter run failed")
            if now >= times[2]:
                try:
                    self._run_upstream_sync()
                except Exception:
                    self.logger.exception("Admin upstream sync run failed")
            if now >= times[3]:
                try:
                    self._run_process_scout()
                except Exception:
                    self.logger.exception("Admin process scout run failed")
            if now >= times[4]:
                try:
                    self._run_wiki_ops_audit()
                except Exception:
                    self.logger.exception("Admin wiki ops audit run failed")
            if now >= times[5]:
                try:
                    self._run_doc_hygiene()
                except Exception:
                    self.logger.exception("Admin doc hygiene run failed")

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

    def _run_process_scout(self, *, force: bool = False) -> dict[str, Any]:
        from company_brain.agents.admin.process_scout import ProcessScoutAgent, process_scout_config
        from company_brain.runtime.fleet_gate import dispatch_slot

        cfg = process_scout_config()
        if not cfg.get("enabled", True):
            return {"status": "skipped", "reason": "disabled"}
        month = previous_month()
        store = StateStore()
        key = f"admin_manager:process_scout:{month}"
        if not force and store.get(key):
            return {"status": "skipped", "month": month, "reason": "already_ran"}
        with dispatch_slot(self.name) as allowed:
            if not allowed:
                return {"status": "skipped", "reason": "fleet_paused"}
            runtime = get_runtime()
            with ambient_scope(
                manager=self.name,
                run_id=new_run_id(),
                reason="process_scout",
            ):
                result = runtime.run(ProcessScoutAgent, self.config, month=month, sync=True)
            store.set(key, {"at": datetime.now().isoformat()})
            return {"status": "ok", "process_scout": result}

    def _run_wiki_ops_audit(self, *, force: bool = False) -> dict[str, Any]:
        from company_brain.agents.admin.wiki_ops_audit import (
            WikiOpsAuditAgent,
            wiki_ops_audit_config,
        )
        from company_brain.runtime.fleet_gate import dispatch_slot

        cfg = wiki_ops_audit_config()
        if not cfg.get("enabled", True):
            return {"status": "skipped", "reason": "disabled"}
        month = previous_month()
        store = StateStore()
        key = f"admin_manager:wiki_ops_audit:{month}"
        if not force and store.get(key):
            return {"status": "skipped", "month": month, "reason": "already_ran"}
        with dispatch_slot(self.name) as allowed:
            if not allowed:
                return {"status": "skipped", "reason": "fleet_paused"}
            runtime = get_runtime()
            with ambient_scope(
                manager=self.name,
                run_id=new_run_id(),
                reason="wiki_ops_audit",
            ):
                result = runtime.run(WikiOpsAuditAgent, self.config, month=month, sync=True)
            store.set(key, {"at": datetime.now().isoformat()})
            return {"status": "ok", "wiki_ops_audit": result}

    def _run_doc_hygiene(self, *, force: bool = False) -> dict[str, Any]:
        from company_brain.agents.admin.doc_hygiene import (
            DocHygieneAgent,
            current_quarter_period,
            doc_hygiene_config,
        )
        from company_brain.runtime.fleet_gate import dispatch_slot

        cfg = doc_hygiene_config()
        if not cfg.get("enabled", True):
            return {"status": "skipped", "reason": "disabled"}
        now = datetime.now()
        if not force and now.month not in set(cfg.get("months") or [1, 4, 7, 10]):
            return {"status": "skipped", "reason": "not_quarter_month"}
        period = current_quarter_period()
        store = StateStore()
        key = f"admin_manager:doc_hygiene:{period}"
        if not force and store.get(key):
            return {"status": "skipped", "period": period, "reason": "already_ran"}
        with dispatch_slot(self.name) as allowed:
            if not allowed:
                return {"status": "skipped", "reason": "fleet_paused"}
            runtime = get_runtime()
            with ambient_scope(
                manager=self.name,
                run_id=new_run_id(),
                reason="doc_hygiene",
            ):
                result = runtime.run(DocHygieneAgent, self.config, period=period, sync=True)
            store.set(key, {"at": datetime.now().isoformat()})
            return {"status": "ok", "doc_hygiene": result}

    def _next_upstream_time(self, now: datetime) -> datetime:
        from company_brain.agents.admin.upstream_sync import upstream_sync_config

        cfg = upstream_sync_config()
        return _next_day_of_month(
            now, day=int(cfg.get("day") or 15), time_str=str(cfg.get("time") or "10:00")
        )

    def _next_process_scout_time(self, now: datetime) -> datetime:
        from company_brain.agents.admin.process_scout import process_scout_config

        cfg = process_scout_config()
        return _next_day_of_month(
            now, day=int(cfg.get("day") or 7), time_str=str(cfg.get("time") or "09:30")
        )

    def _next_wiki_ops_time(self, now: datetime) -> datetime:
        from company_brain.agents.admin.wiki_ops_audit import wiki_ops_audit_config

        cfg = wiki_ops_audit_config()
        return _next_day_of_month(
            now, day=int(cfg.get("day") or 8), time_str=str(cfg.get("time") or "09:45")
        )

    def _next_doc_hygiene_time(self, now: datetime) -> datetime:
        from company_brain.agents.admin.doc_hygiene import doc_hygiene_config

        cfg = doc_hygiene_config()
        months = sorted(set(int(m) for m in (cfg.get("months") or [1, 4, 7, 10])))
        day = int(cfg.get("day") or 10)
        return next_calendar_run(
            now,
            day=day,
            at=parse_hhmm(str(cfg.get("time") or "10:00")),
            months=months,
        )

    def _next_run_time(self, now: datetime) -> datetime:
        cfg = llm_ops_config()
        return _next_day_of_month(
            now, day=int(cfg.get("day") or 1), time_str=str(cfg.get("time") or "09:00")
        )

    def _next_investor_time(self, now: datetime) -> datetime:
        cfg = _investor_cfg()
        return _next_day_of_month(
            now, day=int(cfg.get("run_day") or 3), time_str=str(cfg.get("time") or "09:00")
        )
