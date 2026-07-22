"""PostHog Manager — persistent weekly dispatcher for product analytics specialists.

Checks PostHog according to ``config/product.yaml`` → ``posthog`` schedule
(default Monday 09:00 in the configured timezone). Idles otherwise.

SDK: Neither (orchestration only). Read-only specialists; no PostHog mutates.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.product.posthog import posthog_client as ph
from company_brain.agents.product.posthog import posthog_config as cfg
from company_brain.agents.product.shared.product_slack import product_notifier
from company_brain.config import AppConfig
from company_brain.notify import ACTIONABLE, Signal

WEEK_KEY = "posthog_manager:week"
FAIL_KEY = "posthog_manager:fail_count"
FAIL_ALERT_AFTER = 2


class PosthogManager(BaseAgent):
    """Persistent manager for the PostHog platform within product."""

    name = "posthog_manager"
    track_duration = False

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()

    def should_run(self, **kwargs: Any) -> bool:
        return cfg.enabled() and ph.posthog_is_configured()

    def run(self, *, once: bool = False, **kwargs: Any) -> Any:
        if once:
            return self.run_once(**kwargs)
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        from company_brain.admin_console.heartbeats import record_heartbeat

        self.logger.info(
            "PostHog manager starting (weekday=%s hour=%02d:%02d tz=%s)",
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
            self.logger.info("Next PostHog snapshot at %s (sleep %.0fs)", nxt.isoformat(), wait)
            await asyncio.sleep(chunk)
            if datetime.now(cfg.tz()) < nxt:
                continue
            try:
                self.run_once()
            except Exception:
                self.logger.exception("PostHog manager run failed")
                self._record_failure()

    def run_once(self, *, force: bool = False) -> dict[str, Any]:
        """Dispatch the four snapshot specialists for the current week."""
        from company_brain.admin_console.heartbeats import record_dispatch, record_heartbeat

        now = datetime.now(cfg.tz())
        week = iso_week_key(now)
        record_heartbeat(self.name, detail=f"run_once:{week}")
        if not force and self._state.get(WEEK_KEY) == week:
            self.logger.info("PostHog snapshots already done for %s — skip", week)
            return {"status": "skipped", "week": week}

        from company_brain.agents.product.posthog.experiment_watch import ExperimentWatchAgent
        from company_brain.agents.product.posthog.feature_usage import FeatureUsageAgent
        from company_brain.agents.product.posthog.signup_funnel import SignupFunnelAgent
        from company_brain.agents.product.posthog.tracking_audit import TrackingAuditAgent
        from company_brain.runtime import get_runtime

        runtime = get_runtime()
        results: dict[str, Any] = {"week": week}
        try:
            audit = runtime.run(TrackingAuditAgent, self.config)
            results["tracking_audit"] = audit
            usage = runtime.run(FeatureUsageAgent, self.config)
            results["feature_usage"] = usage
            exp = runtime.run(ExperimentWatchAgent, self.config)
            results["experiment_watch"] = exp
            funnel = runtime.run(SignupFunnelAgent, self.config)
            results["signup_funnel"] = funnel
        except Exception:
            self._record_failure()
            raise

        self._state.set(WEEK_KEY, week)
        self._state.set(FAIL_KEY, 0)
        self._maybe_notify(
            audit if isinstance(audit, dict) else {},
            usage if isinstance(usage, dict) else {},
            exp if isinstance(exp, dict) else {},
            funnel if isinstance(funnel, dict) else {},
        )
        record_dispatch(self.name, result_status="ok")
        return {"status": "ok", **results}

    def _maybe_notify(
        self,
        audit: dict[str, Any],
        usage: dict[str, Any],
        exp: dict[str, Any],
        funnel: dict[str, Any],
    ) -> None:
        lines: list[str] = []
        new_missing = list(audit.get("new_missing") or [])
        if new_missing:
            lines.append("PostHog tracking gaps (no matching flag/event for wiki features):")
            for feature in new_missing[:20]:
                lines.append(f"• {feature}")
            if len(new_missing) > 20:
                lines.append(f"• …and {len(new_missing) - 20} more")

        new_drops = list(usage.get("new_usage_drops") or [])
        if new_drops:
            lines.append("Significant feature usage drops (L7D vs prior week) — action item:")
            for item in new_drops[:20]:
                lines.append(
                    f"• {item.get('feature')}: {item.get('prior')} → {item.get('current')} "
                    f"(-{item.get('drop_pct')}%)"
                )
            if len(new_drops) > 20:
                lines.append(f"• …and {len(new_drops) - 20} more")

        newly = list(exp.get("newly_conclusive") or [])
        if newly:
            lines.append("PostHog experiment(s) look conclusive (human decision needed):")
            for item in newly:
                lines.append(
                    f"• {item.get('name')}: winner `{item.get('winner')}` "
                    f"(p≈{float(item.get('probability') or 0):.0%})"
                )

        new_zero = list(funnel.get("new_zero_steps") or [])
        if new_zero:
            lines.append("Signup funnel step(s) have zero events (check PostHog instrumentation):")
            for step in new_zero:
                lines.append(f"• {step}")

        if not lines:
            return
        product_notifier().emit(Signal(text="\n".join(lines), severity=ACTIONABLE))

    def _record_failure(self) -> None:
        try:
            count = int(self._state.get(FAIL_KEY) or 0) + 1
        except (TypeError, ValueError):
            count = 1
        self._state.set(FAIL_KEY, count)
        if count >= FAIL_ALERT_AFTER:
            product_notifier().emit(
                Signal(
                    text=(
                        f"PostHog manager failed {count} times in a row "
                        "(auth/API). Check POSTHOG_* credentials and project access."
                    ),
                    severity=ACTIONABLE,
                )
            )


def iso_week_key(when: datetime) -> str:
    iso = when.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def next_run_at(now: datetime) -> datetime:
    """Next scheduled weekday at run_hour:run_minute in ``now``'s tz."""
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
