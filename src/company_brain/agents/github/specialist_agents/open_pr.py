"""Open PR Agent.

SDK: Anthropic Claude Agent SDK — this agent connects to GitHub (read) and Notion
(write) as data sources, benefits from the large context window to summarize PR
details, and operates as a single competent assistant.

Reads open pull requests from GitHub and maintains a Notion page with the current
list. Uses discover-or-create on first run to find or create the "Open PRs" page.
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.github.gh import list_open_prs
from company_brain.agents.github.notion_binding import ensure_notion_page
from company_brain.config import AppConfig

logger = logging.getLogger(__name__)

AGENT_KEY = "open_pr"
SEARCH_TERMS = ["Open PRs", "Open Pull Requests", "Pull Requests"]
CREATE_TITLE = "Open PRs"


class OpenPRAgent(BaseAgent):
    """Reads open PRs from GitHub and updates a Notion page with the list."""

    name = "github_open_pr"

    def __init__(self, config: AppConfig, repo: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.repo = repo
        self._page_id: str | None = None

    def setup(self) -> None:
        self._page_id = ensure_notion_page(AGENT_KEY, SEARCH_TERMS, CREATE_TITLE)
        if not self._page_id:
            raise RuntimeError("Could not bind to a Notion page for Open PRs")

    def run(self, **kwargs: Any) -> Any:
        prs = list_open_prs(self.repo)
        self.logger.info("Found %d open PRs", len(prs))

        content = self._format_pr_list(prs)
        self._update_notion_page(content)
        return {"pr_count": len(prs)}

    def _format_pr_list(self, prs: list[dict[str, Any]]) -> str:
        if not prs:
            return "No open pull requests."

        lines = []
        for pr in prs:
            author = pr.get("author", {}).get("login", "unknown")
            title = pr.get("title", "Untitled")
            number = pr.get("number", "?")
            url = pr.get("url", "")
            branch = pr.get("headRefName", "")
            review = pr.get("reviewDecision", "PENDING")
            lines.append(
                f"- **#{number}** [{title}]({url}) by @{author} "
                f"(`{branch}`) — {review}"
            )
        return "\n".join(lines)

    def _update_notion_page(self, content: str) -> None:
        """Overwrite the Notion page body with current PR list."""
        try:
            subprocess.run(
                ["ntn", "page", "update", self._page_id, "--body", content],
                capture_output=True, text=True, check=True,
            )
            self.logger.info("Updated Notion page %s", self._page_id)
        except subprocess.CalledProcessError as e:
            self.logger.error("Failed to update Notion page: %s", e.stderr)
        except FileNotFoundError:
            self.logger.error("Notion CLI (ntn) not found")
