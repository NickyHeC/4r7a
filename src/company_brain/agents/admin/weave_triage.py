"""Weave Triage — classify @weave mentions and write change-request pages.

SDK: Neither (heuristics + wiki writes + optional Notion DB).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.admin.change_request import (
    CHANGE_REQUEST_DIR,
    ChangeRequest,
    auto_dispatch_allowed,
    change_request_body,
    change_request_frontmatter,
    classify_change_class,
    needs_admin_approval,
    new_request_id,
    title_from_text,
)
from company_brain.agents.admin.weave_auth import can_invoke_weave, resolve_weave_requester
from company_brain.agents.admin.weave_notion import (
    create_change_request_row,
    list_approved_requests,
)
from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.slack.rate_limits import (
    RateLimitExceeded,
    check_weave_submission_limit,
)
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import UPDATE, write_wiki_page


class WeaveTriageAgent(BaseAgent):
    """Triage @weave system-change requests."""

    name = "weave_triage"
    WRITE_MODE = UPDATE

    def run(
        self,
        *,
        slack_user_id: str,
        text: str,
        channel_id: str = "",
        thread_ts: str = "",
        permalink: str = "",
        poll_approvals: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if poll_approvals:
            return self.poll_approved_dispatch()

        requester = resolve_weave_requester(slack_user_id)
        allowed, reason = can_invoke_weave(requester)
        if not allowed:
            return {"status": "rejected", "reason": reason}

        try:
            check_weave_submission_limit(slack_user_id)
        except RateLimitExceeded as exc:
            return {"status": "rate_limited", "limit": exc.limit, "window": exc.window}

        member_key = requester.member_key or "unknown"
        change_class = classify_change_class(text)
        req = ChangeRequest(
            request_id=new_request_id(),
            title=title_from_text(text),
            body=text,
            change_class=change_class,
            requester_member=member_key,
            requester_slack_id=slack_user_id,
            slack_channel=channel_id,
            slack_thread_ts=thread_ts,
            slack_permalink=permalink,
            status="submitted",
        )

        if needs_admin_approval(change_class):
            req.status = "awaiting_approval"
        elif auto_dispatch_allowed(change_class):
            req.status = "approved"

        notion_id = create_change_request_row(req)
        req.notion_page_id = notion_id

        write_wiki_page(
            req.wiki_path,
            f"Change Request — {member_key}",
            change_request_body(req),
            mode=self.WRITE_MODE,
            section="admin",
            type_="change_request",
            extra_frontmatter=change_request_frontmatter(req),
        )

        dispatch_result: dict[str, Any] | None = None
        if req.status == "approved":
            dispatch_result = self._dispatch_weave(req)
            self._notify(req, dispatched=True)
        else:
            self._notify(req, dispatched=False)

        return {
            "status": "submitted",
            "request_id": req.request_id,
            "change_class": change_class,
            "wiki_path": req.wiki_path,
            "dispatch": dispatch_result,
        }

    def poll_approved_dispatch(self) -> dict[str, Any]:
        """Poll Notion for approved requests and dispatch weave (admin approval path)."""
        dispatched = 0
        for row in list_approved_requests():
            title = row.get("title") or ""
            if not title:
                continue
            from company_brain.wiki.publish import read_wiki_page

            rel = _match_wiki_path_for_title(title)
            if not rel:
                continue
            body = read_wiki_page(rel)
            if "dispatched" in body.lower() and "**PR:**" in body:
                continue
            req = _request_from_wiki(rel, body)
            if req is None:
                continue
            req.status = "approved"
            result = self._dispatch_weave(req)
            if result.get("status") == "dispatched":
                dispatched += 1
        return {"status": "ok", "dispatched": dispatched}

    def _dispatch_weave(self, req: ChangeRequest) -> dict[str, Any]:
        from company_brain.agents.admin.weave import WeaveAgent
        from company_brain.runtime import get_runtime

        return get_runtime().run(WeaveAgent, self.config, request=req)

    def _notify(self, req: ChangeRequest, *, dispatched: bool) -> None:
        from company_brain.agents.admin.weave_notify import weave_admin_notifier

        if dispatched:
            text = (
                f"*Weave dispatched* (`{req.change_class}`)\n"
                f"*{req.title}* by {req.requester_member}\n"
                f"`{req.wiki_path}`"
            )
            severity = ACTIONABLE
        elif needs_admin_approval(req.change_class):
            text = (
                f"*Weave approval needed* (`{req.change_class}`)\n"
                f"*{req.title}* by {req.requester_member}\n"
                f"Approve in Notion, then run `company-brain weave poll-approvals`."
            )
            severity = ACTIONABLE
        else:
            text = (
                f"*Weave submitted* (`{req.change_class}`)\n*{req.title}* by {req.requester_member}"
            )
            severity = ACTIONABLE
        weave_admin_notifier().emit(Signal(text=text, severity=severity))


def _match_wiki_path_for_title(title: str) -> str | None:
    from company_brain.config import resolve_wiki_dir
    from company_brain.wiki.store import LocalWikiStore

    store = LocalWikiStore(root=resolve_wiki_dir())
    base = store.abspath(CHANGE_REQUEST_DIR)
    if not base.is_dir():
        return None
    for path in sorted(base.glob("*.md")):
        rel = f"{CHANGE_REQUEST_DIR}/{path.name}"
        try:
            doc = store.read(rel)
        except FileNotFoundError:
            continue
        if str(doc.frontmatter.get("title") or "") == title:
            return rel
    return None


def _request_from_wiki(rel_path: str, body: str) -> ChangeRequest | None:
    from company_brain.config import resolve_wiki_dir
    from company_brain.wiki.store import LocalWikiStore

    store = LocalWikiStore(root=resolve_wiki_dir())
    try:
        doc = store.read(rel_path)
    except FileNotFoundError:
        return None
    fm = doc.frontmatter
    request_id = rel_path.rsplit("/", 1)[-1].replace(".md", "")
    return ChangeRequest(
        request_id=request_id,
        title=str(fm.get("title") or title_from_text(body)),
        body=doc.body,
        change_class=str(fm.get("change_class") or "agent_behavior"),
        requester_member=str(fm.get("requester") or ""),
        requester_slack_id=str(fm.get("requester_slack_id") or ""),
        slack_permalink=str(fm.get("slack_thread") or ""),
        status=str(fm.get("status") or "approved"),
        pr_url=str(fm.get("pr_url") or ""),
        notion_page_id=str(fm.get("notion_page_id") or ""),
    )
