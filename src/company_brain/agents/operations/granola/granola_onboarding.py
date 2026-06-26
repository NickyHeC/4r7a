"""Granola Onboarding Agent.

Runs once on first Granola connection: backfills historical meeting notes by
running ``granola_ingest`` for each day in the configured window, then starts
the persistent ``granola_meeting_watch`` loop (post-meeting ingest + weekly miss check).

SDK: Neither (orchestration only).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.granola.granola_ingest import GranolaIngestAgent
from company_brain.agents.operations.shared.granola_config import (
    backfill_days,
    granola_is_configured,
)

AGENT_KEY = "granola_onboarding"


class GranolaOnboardingAgent(BaseAgent):
    """One-time Granola setup: historical backfill, hand off to daily ingest."""

    name = "granola_onboarding"

    def run(
        self,
        *,
        start_manager: bool = True,
        backfill_days_override: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not granola_is_configured():
            self.logger.warning("Granola not configured — skipping onboarding")
            return {"status": "not_configured"}

        days = backfill_days_override if backfill_days_override is not None else backfill_days()
        self.logger.info("Starting Granola onboarding (%d-day backfill)", days)

        ingest = GranolaIngestAgent(self.config)
        today = date.today()
        day_results: list[dict[str, Any]] = []
        total_notes = 0

        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            try:
                result = ingest.run_once(target_date=day)
            except Exception:
                self.logger.exception("Backfill failed for %s", day.isoformat())
                result = {"status": "error", "date": day.isoformat()}
            day_results.append(result)
            if result.get("status") == "ok":
                total_notes += int(result.get("notes") or 0)
            self.logger.info("Backfill %s: %s", day.isoformat(), result.get("status"))

        if start_manager:
            self._start_ingest()

        self.logger.info(
            "Granola onboarding complete (%d notes across %d days)",
            total_notes,
            days,
        )
        return {
            "status": "ok",
            "backfill_days": days,
            "total_notes": total_notes,
            "days": day_results,
        }

    def _start_ingest(self) -> None:
        from company_brain.agents.operations.granola.granola_meeting_watch import (
            GranolaMeetingWatchAgent,
        )
        from company_brain.runtime import get_runtime

        self.logger.info(
            "Backfill complete — starting granola_meeting_watch "
            "(post-meeting ingest + weekly miss check)",
        )
        try:
            get_runtime().start(GranolaMeetingWatchAgent, self.config)
        except Exception:
            self.logger.exception("Failed to start granola_meeting_watch")
