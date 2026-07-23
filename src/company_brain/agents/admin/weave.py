"""Weave — dispatch approved change requests (proposal PR or implement+prove).

Default builder backend is Codex on the smol registry image (Weave dispatches and
injects the API key). Opt-in ``in_house`` uses a company-brain guest runner.
``config_only`` only; out-of-allow-list work escalates to the admin session queue.

SDK: Neither (git + GitHub CLI + smolvm builder session).
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
from company_brain.agents.admin.weave_allowlist import check_changed_paths
from company_brain.agents.admin.weave_builder_config import (
    BUILDER_CODEX,
    BUILDER_IN_HOUSE,
    BUILDER_OFF,
    resolve_builder,
    weave_builder_config,
)
from company_brain.agents.admin.weave_codex import implement_with_codex
from company_brain.agents.admin.weave_escalate import escalate_to_admin_session
from company_brain.agents.admin.weave_in_house import implement_in_house
from company_brain.agents.admin.weave_notion import update_change_request_row
from company_brain.agents.admin.weave_prove import prove_worktree
from company_brain.agents.admin.weave_worktree import create_weave_worktree
from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.github.gh import create_pull_request, gh_available
from company_brain.config import PROJECT_ROOT
from company_brain.runtime.builder_session import builder_runtime_available
from company_brain.wiki.publish import UPDATE, write_wiki_page

logger = logging.getLogger(__name__)

PROPOSAL_DIR = "docs/weave-requests"


class WeaveAgent(BaseAgent):
    """Dispatch an approved change request as a draft GitHub PR."""

    name = "weave"
    track_duration = False
    WRITE_MODE = UPDATE

    def run(
        self,
        *,
        request: ChangeRequest | None = None,
        builder: str | None = None,
        sync: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if request is None:
            return {"status": "skipped", "reason": "no_request"}

        backend = resolve_builder(builder)
        if request.change_class == "config_only" and backend != BUILDER_OFF:
            result = self._implement_and_prove(request, backend=backend, sync=sync)
        else:
            result = self._proposal_only(request)

        self._persist_request(request, sync=sync)
        self._notify(request, result)
        return result

    def _implement_and_prove(
        self,
        request: ChangeRequest,
        *,
        backend: str,
        sync: bool,
    ) -> dict[str, Any]:
        cfg = weave_builder_config()
        fail_closed = bool(cfg.get("prove_fail_closed", True))
        available = builder_runtime_available()

        # Codex requires the guest VM; in_house can run deterministic offline edits
        # on an ephemeral worktree without smolvm (still never touches PROJECT_ROOT).
        needs_vm = backend == BUILDER_CODEX
        if needs_vm and not available and fail_closed:
            escalate_to_admin_session(
                request,
                reason="builder_unavailable",
                detail="smolvm sandbox not available for Codex implement+prove",
                sync=sync,
            )
            request.status = "escalated"
            return {"status": "escalated", "reason": "builder_unavailable", "builder": backend}

        branch = f"weave/{request.request_id}"
        wt = create_weave_worktree(branch)
        try:
            if backend == BUILDER_CODEX:
                built = implement_with_codex(request, wt)
            elif backend == BUILDER_IN_HOUSE:
                built = implement_in_house(request, wt, use_vm=available)
            else:
                return {"status": "failed", "reason": "unknown_builder", "builder": backend}

            if built.status == "escalate":
                escalate_to_admin_session(
                    request,
                    reason=built.reason or "builder_escalate",
                    detail=built.output[:500] if built.output else "",
                    sync=sync,
                )
                request.status = "escalated"
                return {
                    "status": "escalated",
                    "reason": built.reason,
                    "builder": backend,
                }

            if built.status != "ok":
                request.status = "failed"
                return {
                    "status": "failed",
                    "reason": built.reason or "implement_failed",
                    "builder": backend,
                    "output": built.output[-1000:] if built.output else "",
                }

            paths = built.changed_paths or wt.changed_paths()
            ok, bad = check_changed_paths(paths, cfg=cfg)
            if not ok:
                escalate_to_admin_session(
                    request,
                    reason="allowlist_violation",
                    disallowed_paths=bad,
                    sync=sync,
                )
                request.status = "escalated"
                return {
                    "status": "escalated",
                    "reason": "allowlist_violation",
                    "disallowed_paths": bad,
                    "builder": backend,
                }

            # Always write bookkeeping proposal in worktree for the PR body trail.
            self._write_proposal_file(wt.path, request)

            prove = prove_worktree(
                wt.path,
                fail_closed=fail_closed,
                builder_available=True if backend == BUILDER_IN_HOUSE else available,
            )
            if not prove.get("ok"):
                request.status = "failed"
                return {
                    "status": "failed",
                    "reason": prove.get("reason") or "prove_failed",
                    "prove": prove,
                    "builder": backend,
                }

            if not wt.commit_all(f"Weave: {request.title}"):
                request.status = "failed"
                return {"status": "failed", "reason": "commit_failed", "builder": backend}

            pr_url = self._open_pr_from_worktree(request, wt)
            request.status = "dispatched"
            request.pr_url = pr_url or ""
            if pr_url:
                from company_brain.runtime.fleet_gate import request_redeploy

                request_redeploy(
                    pr_url=pr_url,
                    by="weave",
                    note="Agent-code PR opened; redeploy managers after merge",
                )
            return {
                "status": "dispatched" if pr_url else "recorded",
                "pr_url": pr_url,
                "builder": backend,
                "changed_paths": paths,
                "reason": None if pr_url else "pr_not_created",
            }
        finally:
            wt.cleanup()

    def _proposal_only(self, request: ChangeRequest) -> dict[str, Any]:
        """Legacy path: markdown proposal PR (no guest implement)."""
        pr_url = self._open_proposal_pr(request)
        request.status = "dispatched"
        request.pr_url = pr_url or ""
        if pr_url:
            return {"status": "dispatched", "pr_url": pr_url, "builder": BUILDER_OFF}
        return {"status": "recorded", "reason": "pr_not_created", "builder": BUILDER_OFF}

    def _persist_request(self, request: ChangeRequest, *, sync: bool) -> None:
        write_wiki_page(
            request.wiki_path,
            f"Change Request — {request.requester_member}",
            change_request_body(request),
            mode=self.WRITE_MODE,
            section="admin",
            type_="change_request",
            sync=sync,
            extra_frontmatter=change_request_frontmatter(request),
        )
        if request.notion_page_id:
            update_change_request_row(
                request.notion_page_id,
                status=request.status,
                pr_url=request.pr_url,
            )

    def _notify(self, request: ChangeRequest, result: dict[str, Any]) -> None:
        from company_brain.agents.admin.weave_notify import weave_admin_notifier
        from company_brain.notify import ACTIONABLE, Signal

        status = result.get("status")
        if status == "dispatched" and result.get("pr_url"):
            text = f"*Weave PR opened*\n*{request.title}*\n{result['pr_url']}"
        elif status == "escalated":
            text = (
                f"*Weave escalated*\n*{request.title}*\n"
                f"Reason: `{result.get('reason')}` — see `admin/weave-queue.md`"
            )
        elif status == "failed":
            text = f"*Weave failed*\n*{request.title}*\nReason: `{result.get('reason')}`"
        else:
            text = (
                f"*Weave dispatch recorded* (PR not created — check `gh` auth)\n"
                f"*{request.title}*\n`{request.wiki_path}`"
            )
        weave_admin_notifier().emit(Signal(text=text, severity=ACTIONABLE))

    @staticmethod
    def _write_proposal_file(root, request: ChangeRequest) -> str:
        proposal_rel = f"{PROPOSAL_DIR}/{request.request_id}.md"
        proposal_path = root / proposal_rel
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
        return proposal_rel

    def _open_pr_from_worktree(self, request: ChangeRequest, wt) -> str:
        if not gh_available():
            logger.warning("gh CLI not available — skipping PR create")
            return ""
        if not wt.push():
            return ""
        repo = os.getenv("WEAVE_GITHUB_REPO", "").strip()
        try:
            pr = create_pull_request(
                title=f"Weave: {request.title}",
                body=(
                    f"Change request `{request.request_id}` ({request.change_class})\n\n"
                    f"Wiki: `{request.wiki_path}`\n\n"
                    f"{request.body[:4000]}"
                ),
                head=wt.branch,
                repo=repo or None,
                draft=True,
            )
            return str(pr.get("url") or "")
        except Exception:
            self.logger.exception("gh pr create failed")
            return ""

    def _open_proposal_pr(self, request: ChangeRequest) -> str:
        """Host-side proposal markdown PR (non config_only / builder off)."""
        if not gh_available():
            logger.warning("gh CLI not available — skipping PR create")
            return ""

        repo = os.getenv("WEAVE_GITHUB_REPO", "").strip()
        branch = f"weave/{request.request_id}"
        proposal_rel = self._write_proposal_file(PROJECT_ROOT, request)

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
