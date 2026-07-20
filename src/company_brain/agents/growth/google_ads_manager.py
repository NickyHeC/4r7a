"""Google Ads Manager — persistent weekly dispatcher for Ads snapshot specialists.

Checks platforms according to ``config/growth.yaml`` → ``google_ads`` schedule
(default Monday 08:00 in the configured timezone). Idles otherwise.

SDK: Neither (orchestration only). Read-only specialists; no Ads mutates.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.growth.google_ads import google_ads_client as ads
from company_brain.agents.growth.google_ads import google_ads_config as cfg
from company_brain.agents.growth.shared.growth_slack import growth_notifier
from company_brain.config import AppConfig
from company_brain.notify import ACTIONABLE, Signal

WEEK_KEY = "google_ads_manager:week"
FAIL_KEY = "google_ads_manager:fail_count"
FAIL_ALERT_AFTER = 2


class GoogleAdsManager(BaseAgent):
    """Persistent manager for the Google Ads platform within growth."""

    name = "google_ads_manager"
    track_duration = False

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()

    def should_run(self, **kwargs: Any) -> bool:
        return cfg.enabled() and ads.google_ads_is_configured()

    def run(self, *, once: bool = False, **kwargs: Any) -> Any:
        if once:
            return self.run_once(**kwargs)
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        from company_brain.admin_console.heartbeats import record_heartbeat

        self.logger.info(
            "Google Ads manager starting (weekday=%s hour=%02d:%02d tz=%s)",
            cfg.run_weekday(),
            cfg.run_hour(),
            cfg.run_minute(),
            cfg.timezone_name(),
        )
        while True:
            record_heartbeat(self.name, detail="idle")
            now = datetime.now(cfg.tz())
            nxt = next_run_at(now)
            wait = max(1.0, (nxt - now).total_seconds())
            chunk = min(wait, 300.0)
            self.logger.info("Next Google Ads snapshot at %s (sleep %.0fs)", nxt.isoformat(), wait)
            await asyncio.sleep(chunk)
            if datetime.now(cfg.tz()) < nxt:
                continue
            try:
                self.run_once()
            except Exception:
                self.logger.exception("Google Ads manager run failed")
                self._record_failure()

    def run_once(self, *, force: bool = False) -> dict[str, Any]:
        """Dispatch the three snapshot specialists for the current week."""
        from company_brain.admin_console.heartbeats import record_dispatch, record_heartbeat

        now = datetime.now(cfg.tz())
        week = iso_week_key(now)
        record_heartbeat(self.name, detail=f"run_once:{week}")
        if not force and self._state.get(WEEK_KEY) == week:
            self.logger.info("Google Ads snapshots already done for %s — skip", week)
            return {"status": "skipped", "week": week}

        from company_brain.agents.growth.google_ads.acquisition_cost import AcquisitionCostAgent
        from company_brain.agents.growth.google_ads.budget_pacing import BudgetPacingAgent
        from company_brain.agents.growth.google_ads.campaign_status import CampaignStatusAgent
        from company_brain.runtime import get_runtime

        runtime = get_runtime()
        results: dict[str, Any] = {"week": week}
        try:
            results["campaign_status"] = runtime.run(CampaignStatusAgent, self.config)
            pacing = runtime.run(BudgetPacingAgent, self.config)
            results["budget_pacing"] = pacing
            results["acquisition_cost"] = runtime.run(AcquisitionCostAgent, self.config)
        except Exception:
            self._record_failure()
            raise

        self._state.set(WEEK_KEY, week)
        self._state.set(FAIL_KEY, 0)
        self._maybe_notify_pacing(pacing if isinstance(pacing, dict) else {})
        record_dispatch(self.name, result_status="ok")
        return {"status": "ok", **results}

    def _maybe_notify_pacing(self, pacing: dict[str, Any]) -> None:
        alerts = list(pacing.get("pacing_alerts") or [])
        if not alerts:
            return
        lines = [
            f"Google Ads budget pacing ≥ {cfg.pacing_alert_threshold() * 100:.0f}% "
            f"with days left in the month:"
        ]
        for item in alerts:
            lines.append(
                f"• {item.get('name')}: {item.get('percent_used', 0):.1f}% used "
                f"(${item.get('spend', 0):,.2f} / ${item.get('period_budget', 0):,.2f}, "
                f"{item.get('days_left')} days left)"
            )
        growth_notifier().emit(Signal(text="\n".join(lines), severity=ACTIONABLE))

    def _record_failure(self) -> None:
        try:
            count = int(self._state.get(FAIL_KEY) or 0) + 1
        except (TypeError, ValueError):
            count = 1
        self._state.set(FAIL_KEY, count)
        if count >= FAIL_ALERT_AFTER:
            growth_notifier().emit(
                Signal(
                    text=(
                        f"Google Ads manager failed {count} times in a row "
                        "(auth/API). Check GOOGLE_ADS_* credentials and Ads API access."
                    ),
                    severity=ACTIONABLE,
                )
            )


def iso_week_key(when: datetime) -> str:
    iso = when.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def next_run_at(now: datetime) -> datetime:
    """Next scheduled Monday (or configured weekday) at run_hour:run_minute in ``now``'s tz."""
    target_wd = cfg.run_weekday()
    target_time = now.replace(
        hour=cfg.run_hour(),
        minute=cfg.run_minute(),
        second=0,
        microsecond=0,
    )
    days_ahead = (target_wd - now.weekday()) % 7
    candidate = target_time + timedelta(days=days_ahead)
    if days_ahead == 0 and now >= target_time:
        candidate = target_time + timedelta(days=7)
    return candidate
