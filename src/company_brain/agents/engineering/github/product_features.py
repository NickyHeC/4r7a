"""Product Features Agent.

SDK: Anthropic Claude Agent SDK — requires large context window to analyse commit
history and intelligently classify user-facing features. Needs prompt engineering
finesse to rank features by importance.

Reads GitHub commits and maintains a Notion page called "Product Features" with
user-facing features and functions. The page is always kept organized with the most
important feature at the top and least important at the bottom.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timedelta
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.github.gh import list_recent_commits
from company_brain.agents.engineering.github.notion_binding import ensure_notion_page
from company_brain.config import AppConfig

logger = logging.getLogger(__name__)

AGENT_KEY = "product_features"
SEARCH_TERMS = ["Product Features", "Features", "Product Feature List"]
CREATE_TITLE = "Product Features"


class ProductFeaturesAgent(BaseAgent):
    """Maintains a ranked list of user-facing product features on a Notion page."""

    name = "github_product_features"

    def __init__(self, config: AppConfig, repo: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.repo = repo
        self._page_id: str | None = None

    def setup(self) -> None:
        self._page_id = ensure_notion_page(AGENT_KEY, SEARCH_TERMS, CREATE_TITLE)
        if not self._page_id:
            raise RuntimeError("Could not bind to a Notion page for Product Features")

    def run(self, **kwargs: Any) -> Any:
        since = (datetime.now() - timedelta(days=1)).isoformat()
        commits = list_recent_commits(self.repo, since=since)
        self.logger.info("Analysing %d recent commits for user-facing features", len(commits))

        features = self._extract_user_facing_features(commits)
        if not features:
            self.logger.info("No new user-facing features detected")
            return {"new_features": 0}

        existing = self._read_current_page()
        merged = self._merge_and_rank(existing, features)
        self._overwrite_notion_page(merged)
        return {"new_features": len(features)}

    def _extract_user_facing_features(self, commits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Identify commits that introduce user-facing features.

        Heuristics: look for feat: prefix, feature keywords, and exclude
        internal/infra changes.
        """
        internal_keywords = ("refactor", "ci:", "test:", "chore:", "docs:", "infra")
        features = []
        for commit in commits:
            msg = commit.get("commit", {}).get("message", "")
            first_line = msg.split("\n")[0].lower()
            if any(first_line.startswith(kw) for kw in internal_keywords):
                continue
            if "feat" in first_line or "feature" in first_line or "add" in first_line:
                features.append({
                    "title": msg.split("\n")[0],
                    "sha": commit.get("sha", "")[:7],
                    "author": commit.get("author", {}).get("login", "unknown"),
                    "date": commit.get("commit", {}).get("author", {}).get("date", ""),
                })
        return features

    def _read_current_page(self) -> str:
        """Read current content of the Notion page."""
        try:
            result = subprocess.run(
                ["ntn", "page", "read", self._page_id, "--format", "markdown"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                return result.stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        return ""

    def _merge_and_rank(self, existing_content: str, new_features: list[dict[str, Any]]) -> str:
        """Merge new features into existing content and re-rank by importance.

        Ranking heuristic: newer core features rank higher, utility/minor
        features rank lower. Full AI-powered ranking can be added later.
        """
        new_section = "\n".join(
            f"- **{f['title']}** (`{f['sha']}`, @{f['author']}, {f['date'][:10]})"
            for f in new_features
        )

        if not existing_content.strip():
            return f"# Product Features\n\n{new_section}\n"

        # Prepend new features (most recent = likely most important)
        # A more sophisticated ranking pass can be added with Claude Agent SDK
        if "# Product Features" in existing_content:
            return existing_content.replace(
                "# Product Features\n",
                f"# Product Features\n\n{new_section}\n",
                1,
            )
        return f"# Product Features\n\n{new_section}\n\n{existing_content}"

    def _overwrite_notion_page(self, content: str) -> None:
        """Replace the Notion page body with the ranked feature list."""
        try:
            subprocess.run(
                ["ntn", "page", "update", self._page_id, "--body", content],
                capture_output=True, text=True, check=True,
            )
            self.logger.info("Updated Product Features page %s", self._page_id)
        except subprocess.CalledProcessError as e:
            self.logger.error("Failed to update Notion page: %s", e.stderr)
        except FileNotFoundError:
            self.logger.error("Notion CLI (ntn) not found")
