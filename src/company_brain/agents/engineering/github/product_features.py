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
from datetime import datetime, timedelta
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.github.gh import list_recent_commits
from company_brain.config import AppConfig
from company_brain.wiki.publish import APPEND, write_wiki_page

logger = logging.getLogger(__name__)

WIKI_PATH = "engineering/github/product-features.md"
TITLE = "Product Features"


class ProductFeaturesAgent(BaseAgent):
    """Maintains user-facing product features in the wiki.

    Append agent: newly detected features are prepended (newest on top).
    """

    name = "github_product_features"
    WRITE_MODE = APPEND

    def __init__(self, config: AppConfig, repo: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.repo = repo

    def run(self, **kwargs: Any) -> Any:
        since = (datetime.now() - timedelta(days=1)).isoformat()
        commits = list_recent_commits(self.repo, since=since)
        self.logger.info("Analysing %d recent commits for user-facing features", len(commits))

        features = self._extract_user_facing_features(commits)
        if not features:
            self.logger.info("No new user-facing features detected")
            return {"new_features": 0}

        section = self._format_features(features)
        page_id = write_wiki_page(
            WIKI_PATH, TITLE, section, mode=self.WRITE_MODE,
            section="engineering/github", type_="report",
        )
        return {"new_features": len(features), "notion_page_id": page_id}

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

    def _format_features(self, features: list[dict[str, Any]]) -> str:
        """Build the new-features section (prepended newest-on-top by append mode)."""
        today = datetime.now().strftime("%Y-%m-%d")
        lines = [f"## Detected {today}", ""]
        lines += [
            f"- **{f['title']}** (`{f['sha']}`, @{f['author']}, {f['date'][:10]})"
            for f in features
        ]
        return "\n".join(lines)
