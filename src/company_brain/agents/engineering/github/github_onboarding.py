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
from company_brain.agents.engineering.github.gh import list_open_prs, list_repos
from company_brain.config import AppConfig
from company_brain.wiki.publish import write_wiki_page

logger = logging.getLogger(__name__)

AGENT_KEY = "github_onboarding"


class GitHubOnboardingAgent(BaseAgent):
    """One-time onboarding: scans all repos, seeds GitHub wiki pages."""

    name = "github_onboarding"

    def __init__(self, config: AppConfig, org: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.org = org

    def run(self, **kwargs: Any) -> Any:
        self.logger.info("Starting GitHub onboarding — scanning all repos")

        repos = list_repos(self.org)
        self.logger.info("Found %d repositories", len(repos))

        summary = self._analyse_repos(repos)
        self._seed_open_prs(repos)
        self._seed_page("engineering/github/feature-updates.md", "Feature Updates")
        self._seed_page("engineering/github/product-features.md", "Product Features")

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

    def _seed_open_prs(self, repos: list[dict[str, Any]]) -> None:
        """Gather all open PRs across repos and seed the Open PRs wiki page."""
        all_prs = []
        for repo in repos:
            repo_name = repo.get("name", "")
            full_name = f"{self.org}/{repo_name}" if self.org else repo_name
            try:
                all_prs.extend(list_open_prs(full_name))
            except Exception:
                self.logger.debug("Could not list PRs for %s", full_name)
        self.logger.info("Found %d total open PRs across all repos", len(all_prs))
        body = f"# Open PRs\n\n{len(all_prs)} open pull request(s) across {len(repos)} repos.\n"
        write_wiki_page(
            "engineering/github/open-prs.md", "Open PRs", body,
            section="engineering/github", type_="report",
        )

    def _seed_page(self, rel_path: str, title: str) -> None:
        body = f"# {title}\n\n_Seeded during GitHub onboarding; populated on the next scheduled run._\n"
        write_wiki_page(rel_path, title, body, section="engineering/github", type_="report")
        self.logger.info("Seeded wiki page %s", rel_path)
