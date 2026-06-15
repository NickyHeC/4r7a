"""Feature Update Agent.

SDK: Anthropic Claude Agent SDK — needs large context window to digest a week's
worth of commits and distill them into major implementations. Single competent
assistant that reads GitHub and writes to Notion.

Reads recent commits from GitHub, filters for major implementations and updates,
and compiles a weekly feature update on the Notion "Feature Updates" page.
Triggered by the GitHub manager every Monday.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timedelta
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.github.gh import list_recent_commits
from company_brain.agents.github.notion_binding import ensure_notion_page
from company_brain.config import AppConfig

logger = logging.getLogger(__name__)

AGENT_KEY = "feature_update"
SEARCH_TERMS = ["Feature Updates", "Weekly Updates", "Feature Update"]
CREATE_TITLE = "Feature Updates"


class FeatureUpdateAgent(BaseAgent):
    """Compiles weekly feature updates from GitHub commits into a Notion page."""

    name = "github_feature_update"

    def __init__(self, config: AppConfig, repo: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.repo = repo
        self._page_id: str | None = None

    def setup(self) -> None:
        self._page_id = ensure_notion_page(AGENT_KEY, SEARCH_TERMS, CREATE_TITLE)
        if not self._page_id:
            raise RuntimeError("Could not bind to a Notion page for Feature Updates")

    def run(self, **kwargs: Any) -> Any:
        since = (datetime.now() - timedelta(days=7)).isoformat()
        commits = list_recent_commits(self.repo, since=since)
        self.logger.info("Found %d commits this week", len(commits))

        major_commits = self._filter_major(commits)
        self.logger.info("Filtered to %d major updates", len(major_commits))

        content = self._format_update(major_commits)
        self._append_to_notion_page(content)
        return {"total_commits": len(commits), "major_updates": len(major_commits)}

    def _filter_major(self, commits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter commits to only include major implementations and updates.

        Heuristics: exclude merge commits, dependency bumps, typo fixes, and
        commits with very short messages indicating trivial changes.
        """
        skip_prefixes = ("merge ", "bump ", "chore:", "chore(deps)", "fix typo", "typo")
        major = []
        for commit in commits:
            msg = commit.get("commit", {}).get("message", "").lower()
            if any(msg.startswith(p) for p in skip_prefixes):
                continue
            if len(msg) < 10:
                continue
            major.append(commit)
        return major

    def _format_update(self, commits: list[dict[str, Any]]) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        header = f"## Week of {today}\n\n"

        if not commits:
            return header + "No major updates this week.\n"

        lines = [header]
        for commit in commits:
            msg = commit.get("commit", {}).get("message", "").split("\n")[0]
            author = commit.get("author", {}).get("login", "unknown")
            sha = commit.get("sha", "")[:7]
            lines.append(f"- `{sha}` {msg} (@{author})")
        return "\n".join(lines) + "\n"

    def _append_to_notion_page(self, content: str) -> None:
        """Prepend the weekly update to the Notion page (newest on top)."""
        try:
            subprocess.run(
                ["ntn", "page", "prepend", self._page_id, "--body", content],
                capture_output=True, text=True, check=True,
            )
            self.logger.info("Updated Notion page %s with weekly feature update", self._page_id)
        except subprocess.CalledProcessError as e:
            self.logger.error("Failed to update Notion page: %s", e.stderr)
        except FileNotFoundError:
            self.logger.error("Notion CLI (ntn) not found")
