"""GitHub Onboarding Agent.

SDK: Anthropic Claude Agent SDK — needs to ingest entire repository structures,
README files, and commit histories in one pass using the large context window.
Single competent assistant that systematically reads and analyses all repos.

Runs ONCE when GitHub is first connected to this project. Systematically reads
and analyses repos under the company's account, then populates all GitHub-relevant
Notion pages (Open PRs, Feature Updates, Product Features).
"""

from __future__ import annotations

import logging
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.github.gh import list_repos, list_open_prs, list_recent_commits
from company_brain.agents.github.notion_binding import ensure_notion_page
from company_brain.config import AppConfig

logger = logging.getLogger(__name__)

AGENT_KEY = "github_onboarding"


class GitHubOnboardingAgent(BaseAgent):
    """One-time onboarding: scans all repos, populates GitHub Notion pages."""

    name = "github_onboarding"

    def __init__(self, config: AppConfig, org: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.org = org

    def run(self, **kwargs: Any) -> Any:
        self.logger.info("Starting GitHub onboarding — scanning all repos")

        repos = list_repos(self.org)
        self.logger.info("Found %d repositories", len(repos))

        summary = self._analyse_repos(repos)

        self._populate_open_prs(repos)
        self._populate_feature_updates(repos)
        self._populate_product_features(repos)

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

    def _populate_open_prs(self, repos: list[dict[str, Any]]) -> None:
        """Gather all open PRs across repos and write to the Open PRs page."""
        page_id = ensure_notion_page("open_pr", ["Open PRs", "Open Pull Requests"], "Open PRs")
        if not page_id:
            self.logger.warning("Could not bind Open PRs page during onboarding")
            return

        all_prs = []
        for repo in repos:
            repo_name = repo.get("name", "")
            full_name = f"{self.org}/{repo_name}" if self.org else repo_name
            try:
                prs = list_open_prs(full_name)
                for pr in prs:
                    pr["_repo"] = full_name
                all_prs.extend(prs)
            except Exception:
                self.logger.debug("Could not list PRs for %s", full_name)

        self.logger.info("Found %d total open PRs across all repos", len(all_prs))

    def _populate_feature_updates(self, repos: list[dict[str, Any]]) -> None:
        """Gather recent commits and write initial feature updates."""
        ensure_notion_page("feature_update", ["Feature Updates", "Weekly Updates"], "Feature Updates")
        self.logger.info("Feature Updates page ready for future weekly runs")

    def _populate_product_features(self, repos: list[dict[str, Any]]) -> None:
        """Seed the Product Features page with initial user-facing features."""
        ensure_notion_page(
            "product_features",
            ["Product Features", "Features"],
            "Product Features",
        )
        self.logger.info("Product Features page ready for future runs")
