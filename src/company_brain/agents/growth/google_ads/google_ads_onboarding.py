"""Google Ads Onboarding — one-shot snapshot, then hand off to the manager.

Runs the three read-only specialists once (no historical backfill — snapshots
only), then starts ``google_ads_manager`` at its next scheduled weekly time.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.google_ads import google_ads_client as ads
from company_brain.agents.growth.google_ads import google_ads_config as cfg
from company_brain.agents.growth.google_ads.acquisition_cost import AcquisitionCostAgent
from company_brain.agents.growth.google_ads.budget_pacing import BudgetPacingAgent
from company_brain.agents.growth.google_ads.campaign_status import CampaignStatusAgent


class GoogleAdsOnboardingAgent(BaseAgent):
    """One-time Google Ads setup: snapshot pages, start weekly manager."""

    name = "google_ads_onboarding"

    def run(self, *, start_manager: bool = True, **kwargs: Any) -> dict[str, Any]:
        if not cfg.enabled():
            return {"status": "disabled"}
        if not ads.google_ads_is_configured():
            return {"status": "not_configured"}

        from company_brain.runtime import get_runtime

        runtime = get_runtime()
        results = {
            "campaign_status": runtime.run(CampaignStatusAgent, self.config),
            "budget_pacing": runtime.run(BudgetPacingAgent, self.config),
            "acquisition_cost": runtime.run(AcquisitionCostAgent, self.config),
        }

        manager_started = False
        if start_manager:
            self._start_manager()
            manager_started = True

        return {
            "status": "ok",
            "snapshots": results,
            "manager_started": manager_started,
        }

    def _start_manager(self) -> None:
        from company_brain.agents.growth.google_ads_manager import GoogleAdsManager
        from company_brain.runtime import get_runtime

        get_runtime().start(GoogleAdsManager, self.config)
