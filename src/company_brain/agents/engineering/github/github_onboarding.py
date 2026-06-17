"""GitHub Onboarding Agent.

Runs ONCE when GitHub is first connected. Like finance_onboarding (which runs
the finance managers to backfill historical periods), this scans the account
and then **runs the GitHub specialist agents to fill their wiki pages** with
real data, rather than writing placeholders.

SDK: Neither (orchestration only) — it sequences the existing specialists.
"""

from __future__ import annotations

import logging
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.github.gh import list_repos
from company_brain.config import AppConfig

logger = logging.getLogger(__name__)

AGENT_KEY = "github_onboarding"


class GitHubOnboardingAgent(BaseAgent):
    """One-time onboarding: scans repos, then runs the GitHub specialists to fill pages."""

    name = "github_onboarding"

    def __init__(self, config: AppConfig, org: str | None = None, repo: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.org = org
        self.repo = repo

    def run(self, **kwargs: Any) -> Any:
        self.logger.info("Starting GitHub onboarding — scanning all repos")

        repos = list_repos(self.org)
        self.logger.info("Found %d repositories", len(repos))

        summary = self._analyse_repos(repos)
        self._backfill()

        self.logger.info("GitHub onboarding complete")
        return summary

    def _analyse_repos(self, repos: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a summary of the company's GitHub presence."""
        return {
            "total_repos": len(repos),
            "public": sum(1 for r in repos if not r.get("isPrivate")),
            "private": sum(1 for r in repos if r.get("isPrivate")),
            "repos": [r.get("name") for r in repos],
        }

    def _backfill(self) -> None:
        """Run each GitHub specialist once to populate its wiki page with real data."""
        from .branch_monitor import BranchMonitorAgent
        from .feature_update import FeatureUpdateAgent
        from .open_pr import OpenPRAgent
        from .product_features import ProductFeaturesAgent

        specialists = [
            OpenPRAgent(self.config, repo=self.repo),
            BranchMonitorAgent(self.config, repo=self.repo, org=self.org),
            FeatureUpdateAgent(self.config, repo=self.repo),
            ProductFeaturesAgent(self.config, repo=self.repo),
        ]
        for agent in specialists:
            try:
                agent.execute()
            except Exception:
                self.logger.exception("Onboarding backfill failed for %s", agent.name)
