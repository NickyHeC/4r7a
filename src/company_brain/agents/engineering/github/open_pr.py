"""Open PR Agent.

SDK: Anthropic Claude Agent SDK — connects to GitHub (read) as a data source and
summarizes open PRs. Output follows the project data flow: write the wiki
Markdown page (source of truth) first, then sync to Notion.

Reads open pull requests from GitHub and maintains the "Open PRs" wiki page.
"""

from __future__ import annotations

import logging
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.github.gh import list_open_prs
from company_brain.config import AppConfig
from company_brain.wiki.publish import UPDATE, write_wiki_page

logger = logging.getLogger(__name__)

WIKI_PATH = "engineering/github/open-prs.md"
TITLE = "Open PRs"


class OpenPRAgent(BaseAgent):
    """Reads open PRs from GitHub and updates the Open PRs wiki page.

    Update agent: the page is overwritten each run with the current PR list.
    """

    name = "github_open_pr"
    WRITE_MODE = UPDATE

    def __init__(self, config: AppConfig, repo: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.repo = repo

    def run(self, **kwargs: Any) -> Any:
        prs = list_open_prs(self.repo)
        self.logger.info("Found %d open PRs", len(prs))

        body = f"# {TITLE}\n\n{self._format_pr_list(prs)}\n"
        page_id = write_wiki_page(
            WIKI_PATH, TITLE, body, mode=self.WRITE_MODE,
            section="engineering/github", type_="report",
        )
        return {"pr_count": len(prs), "notion_page_id": page_id}

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
                f"(`{branch}`) - {review}"
            )
        return "\n".join(lines)
