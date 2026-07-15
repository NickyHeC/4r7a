"""Escalate Weave requests that are too large or out of allow-list to admin sessions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.admin.change_request import ChangeRequest
from company_brain.agents.admin.weave_builder_config import weave_builder_config
from company_brain.llm.admin_notify import wiki_admin_notifier
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import APPEND, write_wiki_page

QUEUE_TITLE = "Weave Admin Queue"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def escalate_to_admin_session(
    request: ChangeRequest,
    *,
    reason: str,
    detail: str = "",
    disallowed_paths: list[str] | None = None,
    sync: bool = True,
) -> dict[str, Any]:
    """Append a queue entry for the monthly admin coding session.

    Writes ``admin/weave-queue.md`` (config ``queue_path``) and notifies admin.
    """
    cfg = weave_builder_config()
    path = str(cfg.get("queue_path") or "admin/weave-queue.md")

    bullets = [
        f"## {_utc_stamp()} — `{request.request_id}`",
        "",
        f"**Title:** {request.title}",
        f"**Class:** {request.change_class}",
        f"**Requester:** {request.requester_member}",
        f"**Reason:** {reason}",
    ]
    if detail:
        bullets.append(f"**Detail:** {detail}")
    if disallowed_paths:
        bullets.append("**Disallowed paths:**")
        bullets.extend(f"- `{p}`" for p in disallowed_paths[:40])
    bullets.extend(["", f"**Change request:** `{request.wiki_path}`", ""])
    section = "\n".join(bullets)

    write_wiki_page(
        path,
        QUEUE_TITLE,
        section,
        mode=APPEND,
        section="admin",
        type_="review",
        sync=sync,
        sync_label="admin_only",
        extra_frontmatter={"queue": "weave_admin"},
    )

    wiki_admin_notifier().emit(
        Signal(
            text=(
                f"*Weave escalated to admin session*\n"
                f"*{request.title}* (`{request.request_id}`)\n"
                f"Reason: {reason}\n"
                f"Queue: `{path}`"
            ),
            severity=ACTIONABLE,
        )
    )
    return {"status": "escalated", "reason": reason, "queue_path": path}
