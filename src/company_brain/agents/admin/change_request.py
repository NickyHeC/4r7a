"""Change request helpers for Weave."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

CHANGE_REQUEST_DIR = "admin/change-request"

CONFIG_ONLY_SIGNALS = (
    "members.yaml",
    "config/",
    "yaml",
    ".env.example",
    "notion.yaml",
    "operations.yaml",
    "engineering.yaml",
)
SECURITY_SIGNALS = (
    "security",
    "auth",
    "token",
    "acl",
    "access control",
    "allow_hosts",
    "bridge",
    "secret",
)
AGENT_SIGNALS = (
    "agent",
    "prompt",
    "behavior",
    "skill",
    "rule",
    "handbook",
    "verify",
    "sdk",
)


@dataclass
class ChangeRequest:
    request_id: str
    title: str
    body: str
    change_class: str
    requester_member: str
    requester_slack_id: str
    slack_channel: str = ""
    slack_thread_ts: str = ""
    slack_permalink: str = ""
    status: str = "submitted"
    pr_url: str = ""
    notion_page_id: str = ""

    @property
    def wiki_path(self) -> str:
        return f"{CHANGE_REQUEST_DIR}/{self.request_id}.md"


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def classify_change_class(text: str) -> str:
    lower = (text or "").lower()
    if any(sig in lower for sig in SECURITY_SIGNALS):
        return "security_ingest"
    if any(sig in lower for sig in AGENT_SIGNALS):
        return "agent_behavior"
    if any(sig in lower for sig in CONFIG_ONLY_SIGNALS):
        return "config_only"
    return "agent_behavior"


def title_from_text(text: str) -> str:
    line = (text or "").strip().splitlines()[0] if text else ""
    cleaned = re.sub(r"<@[^>]+>", "", line).strip()
    return (cleaned[:120] or "Weave change request").strip()


def change_request_body(req: ChangeRequest) -> str:
    lines = [
        f"# Change Request — {req.requester_member}",
        "",
        f"**Status:** {req.status}",
        f"**Class:** {req.change_class}",
        f"**Requester:** {req.requester_member} (`{req.requester_slack_id}`)",
    ]
    if req.slack_permalink:
        lines.append(f"**Slack thread:** {req.slack_permalink}")
    if req.pr_url:
        lines.append(f"**PR:** {req.pr_url}")
    lines.extend(["", "## Request", "", req.body.strip() or "_No details provided._", ""])
    return "\n".join(lines)


def parse_frontmatter_status(body: str) -> str:
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) >= 3:
            import yaml

            fm = yaml.safe_load(parts[1]) or {}
            return str(fm.get("status") or "")
    return ""


def auto_dispatch_allowed(change_class: str) -> bool:
    return change_class == "config_only"


def needs_admin_approval(change_class: str) -> bool:
    return change_class in {"agent_behavior", "security_ingest"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def change_request_frontmatter(req: ChangeRequest) -> dict[str, Any]:
    return {
        "title": f"Change Request — {req.requester_member}",
        "status": req.status,
        "change_class": req.change_class,
        "requester": req.requester_member,
        "requester_slack_id": req.requester_slack_id,
        "slack_thread": req.slack_permalink,
        "pr_url": req.pr_url,
        "notion_page_id": req.notion_page_id,
    }
