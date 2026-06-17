"""Branch Monitor Agent.

Triggered by the GitHub manager every morning. For each repo it maintains two
tables on the "Branch Status" wiki page (mirrored to Notion):

1. Environments — deploy environments (Prod / Preview / Dev) with current deploy,
   source branch, and how far each is ahead/behind prod.
2. Branches / PRs — open PRs with their target env, ahead/behind that target,
   last activity, and a risk verdict.

SDK: Neither (deterministic Python over the read-only GitHub CLI). Comparisons
use `gh api .../compare/base...head` (ahead_by / behind_by). Output is written
Markdown-first via `write_wiki_page`, then synced to Notion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.github import gh
from company_brain.config import AppConfig
from company_brain.wiki.publish import UPDATE, write_wiki_page

WIKI_PATH = "engineering/github/branch-status.md"
TITLE = "Branch Status"

# Default environment -> source branch mapping (override via the `env_branches`
# kwarg). The first entry is treated as production for the ahead/behind compare.
DEFAULT_ENV_BRANCHES: dict[str, str] = {
    "Prod": "main",
    "Preview": "staging",
    "Dev": "develop",
}


class BranchMonitorAgent(BaseAgent):
    """Maintains per-repo environment + branch/PR status tables in the wiki.

    Update agent: the page is overwritten each run with the current status.
    """

    name = "github_branch_monitor"
    WRITE_MODE = UPDATE

    def __init__(
        self,
        config: AppConfig,
        repo: str | None = None,
        org: str | None = None,
        env_branches: dict[str, str] | None = None,
        stale_days: int = 5,
        drift_threshold: int = 20,
        **kwargs: Any,
    ):
        super().__init__(config, **kwargs)
        self.repo = repo
        self.org = org
        self.env_branches = env_branches or DEFAULT_ENV_BRANCHES
        self.stale_days = stale_days
        self.drift_threshold = drift_threshold

    def run(self, **kwargs: Any) -> Any:
        repos = self._target_repos()
        self.logger.info("Monitoring branches for %d repo(s)", len(repos))

        sections = [f"# {TITLE}", "", f"*Updated {datetime.now():%Y-%m-%d %H:%M}*", ""]
        for repo in repos:
            sections.append(self._repo_section(repo))

        body = "\n".join(sections)
        page_id = write_wiki_page(
            WIKI_PATH, TITLE, body, mode=self.WRITE_MODE,
            section="engineering/github", type_="report",
        )
        return {"repos": len(repos), "notion_page_id": page_id}

    # -- repo selection ----------------------------------------------------

    def _target_repos(self) -> list[str]:
        if self.repo:
            return [self.repo]
        repos: list[str] = []
        for r in gh.list_repos(self.org):
            name = r.get("name", "")
            repos.append(f"{self.org}/{name}" if self.org else name)
        return [r for r in repos if r]

    # -- section rendering -------------------------------------------------

    def _repo_section(self, repo: str) -> str:
        prod_branch = self.env_branches.get("Prod") or gh.default_branch(repo)
        lines = [f"## {repo}", ""]
        lines.append(self._environments_table(repo, prod_branch))
        lines.append("")
        lines.append(self._branches_table(repo))
        lines.append("")
        return "\n".join(lines)

    def _environments_table(self, repo: str, prod_branch: str) -> str:
        rows = [
            "| Environment | Current deploy | Source branch | Behind prod | Ahead of prod | Status |",
            "|---|---|---|---|---|---|",
        ]
        branch_heads = {b.get("name"): b.get("commit", {}).get("sha", "")[:7]
                        for b in gh.list_branches(repo)}
        for env, branch in self.env_branches.items():
            sha = branch_heads.get(branch, "-")
            if branch == prod_branch:
                ahead = behind = 0
            else:
                cmp = gh.compare_branches(repo, prod_branch, branch)
                ahead, behind = cmp.get("ahead_by", 0), cmp.get("behind_by", 0)
            status = self._env_status(ahead, behind)
            rows.append(
                f"| {env} | `{sha}` | `{branch}` | {behind} | {ahead} | {status} |"
            )
        return "\n".join(rows)

    def _branches_table(self, repo: str) -> str:
        rows = [
            "| Owner | Branch / PR | Target env | Ahead of target | Behind target "
            "| Last activity | Risk |",
            "|---|---|---|---|---|---|---|",
        ]
        env_by_branch = {b: e for e, b in self.env_branches.items()}
        prs = gh.list_open_prs(repo)
        if not prs:
            rows.append("| _no open PRs_ |  |  |  |  |  |  |")
            return "\n".join(rows)
        for pr in prs:
            owner = pr.get("author", {}).get("login", "unknown")
            head = pr.get("headRefName", "")
            base = pr.get("baseRefName", "")
            num = pr.get("number", "?")
            target_env = env_by_branch.get(base, base or "-")
            cmp = gh.compare_branches(repo, base, head) if base and head else {}
            ahead, behind = cmp.get("ahead_by", "-"), cmp.get("behind_by", "-")
            last = _humanize_age(pr.get("updatedAt") or pr.get("createdAt"))
            risk = self._risk(pr, behind)
            rows.append(
                f"| {owner} | `{head}` (#{num}) | {target_env} | {ahead} | {behind} "
                f"| {last} | {risk} |"
            )
        return "\n".join(rows)

    # -- heuristics --------------------------------------------------------

    def _env_status(self, ahead: int, behind: int) -> str:
        if ahead == 0 and behind == 0:
            return "Stable"
        if ahead >= self.drift_threshold:
            return "Active drift"
        if behind > 0:
            return "Needs sync"
        return "Ahead"

    def _risk(self, pr: dict[str, Any], behind: Any) -> str:
        age_days = _age_days(pr.get("updatedAt") or pr.get("createdAt"))
        if age_days is not None and age_days > self.stale_days:
            return "Stale"
        if pr.get("reviewDecision") == "APPROVED" and behind in (0, "0"):
            return "Ready"
        return "OK"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_days(value: str | None) -> float | None:
    dt = _parse_dt(value)
    if not dt:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400


def _humanize_age(value: str | None) -> str:
    dt = _parse_dt(value)
    if not dt:
        return "-"
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"
