"""HR Manager — persistent dispatcher for LinkedIn pulls and wiki archives.

Checks schedules from ``config/hr.yaml``. Idles otherwise.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.hr import hr_config as cfg
from company_brain.agents.scheduling.calendar import next_calendar_run
from company_brain.config import AppConfig

MONTH_KEY = "hr_manager:linkedin_month"
DAY_KEY = "hr_manager:archive_day"


class HrManager(BaseAgent):
    """Persistent manager for HR lifecycle specialists."""

    name = "hr_manager"
    track_duration = False
    fleet_exempt = True

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()

    def run(self, *, once: bool = False, **kwargs: Any) -> Any:
        if once:
            return self.run_once(**kwargs)
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        from company_brain.admin_console.heartbeats import record_heartbeat

        interval = cfg.poll_interval_minutes()
        self.logger.info(
            "HR manager starting (linkedin day=%s %02d:%02d tz=%s, poll=%dm)",
            cfg.linkedin_run_day(),
            cfg.linkedin_run_hour(),
            cfg.linkedin_run_minute(),
            cfg.timezone_name(),
            interval,
        )
        while True:
            record_heartbeat(self.name, detail="idle")
            try:
                self.run_once()
            except Exception:
                self.logger.exception("HR manager pass failed")
            await asyncio.sleep(interval * 60)

    def run_once(self, *, force: bool = False, **kwargs: Any) -> dict[str, Any]:
        from company_brain.runtime.fleet_gate import dispatch_slot

        with dispatch_slot(self.name) as allowed:
            if not allowed:
                return {"status": "skipped", "reason": "fleet_paused"}
            return self._run_pass(force=force)

    def _run_pass(self, *, force: bool = False) -> dict[str, Any]:
        from company_brain.admin_console.heartbeats import record_dispatch, record_heartbeat
        from company_brain.agents.hr.linkedin.pull import PullAgent
        from company_brain.agents.hr.wiki_archive import WikiArchiveAgent
        from company_brain.runtime import get_runtime

        now = datetime.now(cfg.tz())
        record_heartbeat(self.name, detail=f"run_once:{now.date().isoformat()}")
        runtime = get_runtime()
        results: dict[str, Any] = {"at": now.isoformat()}

        month = f"{now.year:04d}-{now.month:02d}"
        linkedin_due = force or (
            now.day >= cfg.linkedin_run_day()
            and (now.hour, now.minute) >= (cfg.linkedin_run_hour(), cfg.linkedin_run_minute())
            and self._state.get(MONTH_KEY) != month
        )
        if linkedin_due:
            linkedin_result = runtime.run(
                PullAgent,
                self.config,
                force=force,
            )
            results["linkedin_pull"] = linkedin_result
            if isinstance(linkedin_result, dict) and linkedin_result.get("status") == "ok":
                self._state.set(MONTH_KEY, month)
        else:
            results["linkedin_pull"] = {"status": "skipped", "reason": "not_due"}

        day = now.date().isoformat()
        archive_due = force or self._state.get(DAY_KEY) != day
        if archive_due:
            results["wiki_archive"] = runtime.run(
                WikiArchiveAgent,
                self.config,
                force=False,
            )
            self._state.set(DAY_KEY, day)
        else:
            results["wiki_archive"] = {"status": "skipped", "reason": "already_today"}

        record_dispatch(self.name, result_status="ok")
        return {"status": "ok", **results}


def next_linkedin_run_at(now: datetime | None = None) -> datetime:
    """Next scheduled LinkedIn pull instant in HR timezone."""
    now = now or datetime.now(cfg.tz())
    if now.tzinfo is None:
        now = now.replace(tzinfo=cfg.tz())
    else:
        now = now.astimezone(cfg.tz())

    return next_calendar_run(
        now,
        day=cfg.linkedin_run_day(),
        at=time(cfg.linkedin_run_hour(), cfg.linkedin_run_minute()),
    )
