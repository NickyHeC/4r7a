"""Weave — open a draft PR for an approved change request.

v1 is PR-only (no live agent pause/resume). Optionally verifies in a VM sandbox
before opening the PR.

SDK: Neither (git + GitHub CLI + optional sandbox).
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

from company_brain.agents.admin.change_request import (
    ChangeRequest,
    change_request_body,
    change_request_frontmatter,
)
from company_brain.agents.admin.weave_notion import update_change_request_row
from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.github.gh import create_pull_request, gh_available
from company_brain.config import PROJECT_ROOT
from company_brain.runtime import verify_in_sandbox
from company_brain.wiki.publish import UPDATE, write_wiki_page

logger = logging.getLogger(__name__)

PROPOSAL_DIR = "docs/weave-requests"


class WeaveAgent(BaseAgent):
    """Dispatch an approved change request as a draft GitHub PR."""

    name = "weave"

    def run(self, *, request: ChangeRequest | None = None, **kwargs: Any) -> dict[str, Any]:
        if request is None:
            return {"status": "skipped", "reason": "no_request"}

        sandbox_ok = self._verify_in_sandbox()
        if sandbox_ok is False:
            return {"status": "failed", "reason": "sandbox_verification_failed"}

        pr_url = self._open_pr(request)
        request.status = "dispatched"
        request.pr_url = pr_url or ""
        write_wiki_page(
            request.wiki_path,
            f"Change Request — {request.requester_member}",
            change_request_body(request),
            mode=UPDATE,
            section="admin",
            type_="change_request",
            extra_frontmatter=change_request_frontmatter(request),
        )
        if request.notion_page_id:
            update_change_request_row(
                request.notion_page_id,
                status="dispatched",
                pr_url=request.pr_url,
            )

        from company_brain.agents.admin.weave_notify import weave_admin_notifier
        from company_brain.notify import ACTIONABLE, Signal

        if pr_url:
            weave_admin_notifier().emit(
                Signal(
                    text=(f"*Weave PR opened*\n*{request.title}*\n{pr_url}"),
                    severity=ACTIONABLE,
                )
            )
            return {"status": "dispatched", "pr_url": pr_url}

        weave_admin_notifier().emit(
            Signal(
                text=(
                    f"*Weave dispatch recorded* (PR not created — check `gh` auth)\n"
                    f"*{request.title}*\n`{request.wiki_path}`"
                ),
                severity=ACTIONABLE,
            )
        )
        return {"status": "recorded", "reason": "pr_not_created"}

    def _verify_in_sandbox(self) -> bool | None:
        result = verify_in_sandbox(
            ["python", "-m", "compileall", "-q", "src/company_brain"],
            mount=PROJECT_ROOT,
        )
        if result is None:
            return None
        return result

    def _open_pr(self, request: ChangeRequest) -> str:
        if not gh_available():
            logger.warning("gh CLI not available — skipping PR create")
            return ""

        repo = os.getenv("WEAVE_GITHUB_REPO", "").strip()
        branch = f"weave/{request.request_id}"
        proposal_rel = f"{PROPOSAL_DIR}/{request.request_id}.md"
        proposal_path = PROJECT_ROOT / proposal_rel
        proposal_path.parent.mkdir(parents=True, exist_ok=True)
        proposal_path.write_text(
            "\n".join(
                [
                    f"# {request.title}",
                    "",
                    f"**Class:** {request.change_class}",
                    f"**Requester:** {request.requester_member}",
                    "",
                    request.body,
                    "",
                ]
            )
        )

        if not self._git_push_branch(branch, proposal_rel, request):
            return ""

        try:
            pr = create_pull_request(
                title=f"Weave: {request.title}",
                body=(
                    f"Change request `{request.request_id}` ({request.change_class})\n\n"
                    f"Wiki: `{request.wiki_path}`\n\n"
                    f"{request.body[:4000]}"
                ),
                head=branch,
                repo=repo or None,
                draft=True,
            )
            return str(pr.get("url") or "")
        except Exception:
            self.logger.exception("gh pr create failed")
            return ""

    def _git_push_branch(self, branch: str, proposal_rel: str, request: ChangeRequest) -> bool:
        try:
            subprocess.run(
                ["git", "checkout", "-B", branch],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "add", proposal_rel],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            commit = subprocess.run(
                ["git", "commit", "-m", f"Weave: {request.title}"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )
            output = (commit.stdout or "") + (commit.stderr or "")
            if commit.returncode != 0 and "nothing to commit" not in output:
                logger.warning("git commit failed: %s", commit.stderr[-400:])
                return False
            push = subprocess.run(
                ["git", "push", "-u", "origin", branch],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )
            if push.returncode != 0:
                logger.warning("git push failed: %s", push.stderr[-400:])
                return False
            return True
        except (subprocess.CalledProcessError, OSError) as exc:
            logger.warning("git branch setup failed: %s", exc)
            return False
