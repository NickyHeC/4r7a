"""Customer Support orchestrator — classify customer intake and route.

Single cross-platform entry for Slack Connect, internal customer channels, and
Gmail ``Customer`` mail. Bugs → ``engineering/issue/`` + Linear; feature requests
→ product ledger + ranked snapshot; discussions → open threads only.

SDK: Neither (heuristics + wiki writes + optional Linear).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.linear import linear_client
from company_brain.agents.engineering.shared.linear_config import (
    default_priority,
    team_id,
    team_key,
)
from company_brain.agents.operations.shared.operations_slack import customer_support_notifier
from company_brain.config import AppConfig
from company_brain.crm.contacts import display_name_from_from_header, record_interaction_on_contact
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import APPEND, UPDATE, format_append_section, write_wiki_page

FEATURE_REQUEST_LOG = "product/feature-request-log.md"
FEATURE_REQUEST_RANKED = "product/feature-request.md"
FEATURE_REQUEST_LOG_TITLE = "Feature Request Log"
FEATURE_REQUEST_RANKED_TITLE = "Feature Requests"
ISSUE_DIR = "engineering/issue"

BUG_SIGNALS = (
    "bug",
    "broken",
    "crash",
    "error",
    "doesn't work",
    "doesnt work",
    "not working",
    "regression",
    "500",
    "exception",
)
FEATURE_SIGNALS = (
    "feature request",
    "would be nice",
    "wish",
    "could you add",
    "enhancement",
    "please add",
    "request:",
)


@dataclass
class CustomerIntake:
    source: str
    title: str
    body: str
    requester_email: str = ""
    requester_name: str = ""
    permalink: str = ""
    channel: str = ""
    thread_ts: str = ""
    message_ts: str = ""
    mailbox: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def classify_customer_intake(intake: CustomerIntake) -> str:
    """Return ``bug``, ``feature``, or ``discussion`` ($0 heuristics)."""
    text = f"{intake.title}\n{intake.body}".lower()
    if any(sig in text for sig in BUG_SIGNALS):
        return "bug"
    if any(sig in text for sig in FEATURE_SIGNALS):
        return "feature"
    return "discussion"


def issue_slug(title: str, *, number: int | None = None) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]
    if number:
        return f"{number}-{base}" if base else str(number)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{stamp}-{base}" if base else f"{stamp}-issue"


def notion_link_from_page_id(page_id: str | None) -> str:
    if not page_id:
        return ""
    return f"https://www.notion.so/{str(page_id).replace('-', '')}"


class CustomerSupportOrchestrator:
    """Route classified customer intake to wiki + optional Linear."""

    def process(self, intake: CustomerIntake) -> dict[str, Any]:
        category = classify_customer_intake(intake)
        crm_slug = self._record_crm(intake)
        if category == "bug":
            routed = self._route_bug(intake)
        elif category == "feature":
            routed = self._route_feature(intake)
        else:
            routed = self._route_discussion(intake)

        notified = self._notify(intake, category, routed)
        return {
            "category": category,
            "crm_slug": crm_slug,
            "notified": notified,
            **routed,
        }

    def _record_crm(self, intake: CustomerIntake) -> str | None:
        from_hdr = intake.requester_email or intake.requester_name
        if "@" not in from_hdr:
            return None
        section = _interaction_section(intake)
        try:
            return record_interaction_on_contact(
                from_hdr,
                section,
                segment="customer",
                title=intake.requester_name or None,
            )
        except Exception:
            return None

    def _route_bug(self, intake: CustomerIntake) -> dict[str, Any]:
        linear_issue: dict[str, Any] = {}
        if linear_client.linear_is_configured():
            try:
                linear_issue = linear_client.create_issue(
                    title=intake.title[:200] or "Customer bug report",
                    description=_issue_description(intake),
                    team_id=team_id() or None,
                    team_key=team_key() or None,
                    priority=default_priority(),
                )
            except Exception:
                linear_issue = {}

        gh_number = None
        identifier = str(linear_issue.get("identifier") or "")
        if identifier and "-" in identifier:
            try:
                gh_number = int(identifier.split("-", 1)[1])
            except ValueError:
                gh_number = None

        slug = issue_slug(intake.title, number=gh_number)
        rel_path = f"{ISSUE_DIR}/{slug}.md"
        body = _issue_page_body(intake, linear_issue)
        page_id = write_wiki_page(
            rel_path,
            intake.title[:120] or "Customer Issue",
            body,
            mode=UPDATE,
            section="engineering",
            type_="issue",
            extra_frontmatter={
                "origin": intake.source,
                "linear_id": linear_issue.get("identifier", ""),
                "linear_url": linear_issue.get("url", ""),
                "customer": True,
            },
        )
        rebuild_issue_index()
        return {
            "wiki_path": rel_path,
            "linear_id": linear_issue.get("identifier", ""),
            "linear_url": linear_issue.get("url", ""),
            "notion_page_id": page_id,
        }

    def _route_feature(self, intake: CustomerIntake) -> dict[str, Any]:
        heading = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        section = format_append_section(
            heading,
            _feature_log_body(intake),
            trigger=f"customer_support:{intake.source}",
            why=intake.title[:120],
        )
        write_wiki_page(
            FEATURE_REQUEST_LOG,
            FEATURE_REQUEST_LOG_TITLE,
            section,
            mode=APPEND,
            section="product",
            type_="log",
        )
        ranked_body = rebuild_feature_request_ranked()
        write_wiki_page(
            FEATURE_REQUEST_RANKED,
            FEATURE_REQUEST_RANKED_TITLE,
            ranked_body,
            mode=UPDATE,
            section="product",
            type_="report",
        )
        return {"wiki_path": FEATURE_REQUEST_RANKED}

    def _route_discussion(self, intake: CustomerIntake) -> dict[str, Any]:
        if intake.source == "slack" and intake.channel and intake.thread_ts:
            from company_brain.agents.operations.slack.routing import SlackRoutingStore

            store = SlackRoutingStore()
            store.upsert(
                intake.channel,
                intake.thread_ts,
                kind="discussion_pending",
                attention="2. Reply",
                customer=True,
                extracted={
                    "message_ts": intake.message_ts or intake.thread_ts,
                    "permalink": intake.permalink,
                    "customer_support": True,
                    "title_preview": intake.title[:200],
                },
            )
        return {"open_thread": True}

    def _notify(self, intake: CustomerIntake, category: str, routed: dict[str, Any]) -> bool:
        lines = [
            f"*Customer {category}* ({intake.source})",
            f"*{intake.title}*",
        ]
        if intake.requester_name or intake.requester_email:
            who = intake.requester_name or intake.requester_email
            lines.append(f"*From:* {who}")
        if intake.permalink:
            lines.append(f"*Link:* {intake.permalink}")
        if routed.get("linear_url"):
            lines.append(f"*Linear:* {routed['linear_url']}")
        if routed.get("wiki_path"):
            lines.append(f"*Wiki:* `{routed['wiki_path']}`")
        preview = (intake.body or "").strip()[:400]
        if preview:
            lines.extend(["", preview])
        return customer_support_notifier().emit(Signal(text="\n".join(lines), severity=ACTIONABLE))

    def _rebuild_issue_index(self) -> None:
        rebuild_issue_index()


def rebuild_issue_index() -> None:
    from company_brain.config import resolve_wiki_dir
    from company_brain.wiki.store import LocalWikiStore

    store = LocalWikiStore(root=resolve_wiki_dir())
    issue_dir = store.abspath(ISSUE_DIR)
    if not issue_dir.is_dir():
        return
    rows: list[str] = []
    for path in sorted(issue_dir.glob("*.md")):
        if path.name == "_index.md":
            continue
        rel = f"{ISSUE_DIR}/{path.name}"
        try:
            doc = store.read(rel)
        except FileNotFoundError:
            continue
        title = str(doc.frontmatter.get("title") or path.stem)
        linear = doc.frontmatter.get("linear_id") or ""
        rows.append(f"- [{title}]({rel})" + (f" — {linear}" if linear else ""))
    body = "# Issue Index\n\n" + ("\n".join(rows) if rows else "_No issues yet._\n")
    write_wiki_page(
        f"{ISSUE_DIR}/_index.md",
        "Issue Index",
        body,
        mode=UPDATE,
        section="engineering",
        type_="index",
    )


def rebuild_feature_request_ranked() -> str:
    """Parse the feature request log and return a ranked snapshot body."""
    from company_brain.wiki.publish import read_wiki_page

    log = read_wiki_page(FEATURE_REQUEST_LOG)
    counts: dict[str, int] = {}
    samples: dict[str, str] = {}
    for block in re.split(r"\n## ", log):
        if not block.strip():
            continue
        title_match = re.search(r"\*\*Title:\*\*\s*(.+)", block)
        if not title_match:
            continue
        title = title_match.group(1).strip()
        key = title.lower()
        counts[key] = counts.get(key, 0) + 1
        samples.setdefault(key, title)

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    lines = ["# Feature Requests", "", "Ranked by repeat mentions in the request log.", ""]
    if not ranked:
        lines.append("_No feature requests yet._\n")
        return "\n".join(lines)
    lines.append("| Rank | Requests | Title |")
    lines.append("| --- | --- | --- |")
    for idx, (key, count) in enumerate(ranked[:50], start=1):
        lines.append(f"| {idx} | {count} | {samples.get(key, key)} |")
    lines.append("")
    return "\n".join(lines)


def _interaction_section(intake: CustomerIntake) -> str:
    lines = [
        f"### {intake.source.title()} — {datetime.now(timezone.utc):%Y-%m-%d}",
        "",
        f"**{intake.title}**",
        "",
        (intake.body or "")[:2000],
    ]
    if intake.permalink:
        lines.extend(["", f"[Source]({intake.permalink})"])
    return "\n".join(lines)


def _issue_description(intake: CustomerIntake) -> str:
    parts = [intake.body or ""]
    if intake.permalink:
        parts.append(f"\n\nSource: {intake.permalink}")
    if intake.requester_email:
        parts.append(f"\nReporter: {intake.requester_email}")
    return "\n".join(parts).strip()


def _issue_page_body(intake: CustomerIntake, linear_issue: dict[str, Any]) -> str:
    lines = [
        f"# {intake.title}",
        "",
        f"**Origin:** {intake.source}",
        "**Category:** bug",
    ]
    if linear_issue.get("url"):
        lines.append(f"**Linear:** [{linear_issue.get('identifier')}]({linear_issue['url']})")
    if intake.permalink:
        lines.append(f"**Source:** {intake.permalink}")
    lines.extend(["", "## Description", "", intake.body or "_No details provided._", ""])
    return "\n".join(lines)


def _feature_log_body(intake: CustomerIntake) -> str:
    lines = [
        f"**Title:** {intake.title}",
        f"**Source:** {intake.source}",
    ]
    if intake.requester_name or intake.requester_email:
        who = intake.requester_name or display_name_from_from_header(intake.requester_email)
        lines.append(f"**Requester:** {who}")
    if intake.permalink:
        lines.append(f"**Link:** {intake.permalink}")
    lines.extend(["", intake.body[:2000] if intake.body else ""])
    return "\n".join(lines)


class CustomerSupportAgent(BaseAgent):
    """Cross-platform customer support orchestrator."""

    name = "customer_support"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._orchestrator = CustomerSupportOrchestrator()

    def run(self, *, intake: CustomerIntake | None = None, **kwargs: Any) -> dict[str, Any]:
        if intake is None:
            return {"status": "skipped", "reason": "no_intake"}
        return self._orchestrator.process(intake)
