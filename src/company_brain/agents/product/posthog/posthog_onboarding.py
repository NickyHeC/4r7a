"""PostHog Onboarding — one-shot 30-day backfill, then hand off to the manager.

Verifies API access, runs the four read-only specialists (usage/funnel lookback
30 days when prior events exist), then starts ``posthog_manager`` at its next
scheduled weekly time.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.product.posthog import posthog_client as ph
from company_brain.agents.product.posthog import posthog_config as cfg
from company_brain.agents.product.posthog.experiment_watch import ExperimentWatchAgent
from company_brain.agents.product.posthog.feature_usage import FeatureUsageAgent
from company_brain.agents.product.posthog.signup_funnel import SignupFunnelAgent
from company_brain.agents.product.posthog.tracking_audit import TrackingAuditAgent

BACKFILL_DAYS = 30


class PosthogOnboardingAgent(BaseAgent):
    """One-time PostHog setup: snapshot pages (L30D when data exists), start manager."""

    name = "posthog_onboarding"

    def run(self, *, start_manager: bool = True, **kwargs: Any) -> dict[str, Any]:
        if not cfg.enabled():
            return {"status": "disabled"}
        if not ph.posthog_is_configured():
            return {"status": "not_configured"}

        from company_brain.runtime import get_runtime

        runtime = get_runtime()
        has_data = False
        try:
            has_data = ph.has_events_since_days(BACKFILL_DAYS)
        except Exception as exc:
            self.logger.warning("PostHog event existence check failed: %s", exc)

        lookback = BACKFILL_DAYS if has_data else BACKFILL_DAYS
        results = {
            "tracking_audit": runtime.run(TrackingAuditAgent, self.config),
            "feature_usage": runtime.run(FeatureUsageAgent, self.config, lookback_days=lookback),
            "experiment_watch": runtime.run(ExperimentWatchAgent, self.config),
            "signup_funnel": runtime.run(SignupFunnelAgent, self.config, lookback_days=lookback),
        }

        manager_started = False
        if start_manager:
            self._start_manager()
            manager_started = True

        return {
            "status": "ok",
            "has_prior_data": has_data,
            "lookback_days": lookback,
            "snapshots": results,
            "manager_started": manager_started,
        }

    def _start_manager(self) -> None:
        from company_brain.agents.product.posthog_manager import PosthogManager
        from company_brain.runtime import get_runtime

        get_runtime().start(PosthogManager, self.config)
