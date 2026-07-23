"""GitHub Onboarding Agent.

Runs ONCE when GitHub is first connected. Like finance_onboarding (which runs
the finance managers to backfill historical periods), this scans the account
and then **runs the GitHub specialist agents to fill their wiki pages** with
real data, rather than writing placeholders.

When the backfill is done it hands off to the platform's persistent manager:
it starts `github_manager`, whose loop idles until its next scheduled time
(the next morning check) so steady-state runs continue automatically.

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

    def __init__(
        self, config: AppConfig, org: str | None = None, repo: str | None = None, **kwargs: Any
    ):
        super().__init__(config, **kwargs)
        self.org = org
        self.repo = repo

    def run(self, *, start_manager: bool = True, **kwargs: Any) -> Any:
        self.logger.info("Starting GitHub onboarding — scanning all repos")

        repos = list_repos(self.org)
        self.logger.info("Found %d repositories", len(repos))

        summary = self._analyse_repos(repos)
        self._backfill()

        if start_manager:
            self._start_manager()

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
        from company_brain.runtime import get_runtime

        from .branch_monitor import BranchMonitorAgent
        from .feature_update import FeatureUpdateAgent
        from .open_pr import OpenPRAgent
        from .product_features import ProductFeaturesAgent

        specialists = [
            (OpenPRAgent, {"repo": self.repo}),
            (BranchMonitorAgent, {"repo": self.repo, "org": self.org}),
            (FeatureUpdateAgent, {"repo": self.repo}),
            (ProductFeaturesAgent, {"repo": self.repo}),
        ]
        for agent_cls, kwargs in specialists:
            try:
                get_runtime().run(agent_cls, self.config, **kwargs)
            except Exception:
                self.logger.exception("Onboarding backfill failed for %s", agent_cls.name)

    def _start_manager(self) -> None:
        """Hand off to the persistent GitHub manager (runs at its next schedule)."""
        from company_brain.agents.engineering.github_manager import GitHubManager
        from company_brain.runtime import get_runtime

        self.logger.info(
            "Backfill complete — starting github_manager (idles until next morning check)"
        )
        try:
            get_runtime().start(GitHubManager, self.config, repo=self.repo)
        except Exception:
            self.logger.exception("Failed to start github_manager")
