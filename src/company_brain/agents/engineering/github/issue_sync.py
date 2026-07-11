"""GitHub Issue Sync — daily mirror of open issues to the wiki.

Upserts ``engineering/issue/{slug}.md`` pages and rebuilds the issue index.

SDK: Neither (GitHub CLI read + wiki writes).
"""

from __future__ import annotations

import re
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.github.gh import list_issues
from company_brain.agents.operations.customer_support import rebuild_issue_index
from company_brain.config import AppConfig
from company_brain.wiki.publish import UPDATE, write_wiki_page

ISSUE_DIR = "engineering/issue"


class IssueSyncAgent(BaseAgent):
    """Sync GitHub issues into unified engineering/issue wiki pages."""

    name = "issue_sync"
    WRITE_MODE = UPDATE

    def __init__(self, config: AppConfig, repo: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.repo = repo

    def should_run(self, **kwargs: Any) -> bool:
        return bool(self.repo)

    def run(self, **kwargs: Any) -> dict[str, Any]:
        issues = list_issues(self.repo, state="open")
        upserted = 0
        for issue in issues:
            if self._upsert_issue(issue):
                upserted += 1
        rebuild_issue_index()
        return {"issues": len(issues), "upserted": upserted}

    def _upsert_issue(self, issue: dict[str, Any]) -> bool:
        number = int(issue.get("number") or 0)
        title = str(issue.get("title") or f"Issue {number}")
        slug = _issue_slug(number, title)
        rel_path = f"{ISSUE_DIR}/{slug}.md"
        labels = ", ".join(lbl.get("name", "") for lbl in (issue.get("labels") or []))
        author = (issue.get("author") or {}).get("login", "")
        body = (
            "\n".join(
                [
                    f"# {title}",
                    "",
                    f"**GitHub:** [#{number}]({issue.get('url', '')})",
                    f"**State:** {issue.get('state', '')}",
                    f"**Author:** @{author}" if author else "",
                    f"**Labels:** {labels}" if labels else "",
                    "",
                    "## Description",
                    "",
                    str(issue.get("body") or "_No description._"),
                    "",
                ]
            ).strip()
            + "\n"
        )
        write_wiki_page(
            rel_path,
            title,
            body,
            mode=self.WRITE_MODE,
            section="engineering",
            type_="issue",
            extra_frontmatter={
                "github_number": number,
                "github_url": issue.get("url", ""),
                "github_state": issue.get("state", ""),
            },
        )
        return True


def _issue_slug(number: int, title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]
    return f"{number}-{base}" if base else str(number)
