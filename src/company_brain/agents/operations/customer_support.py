"""Customer Support orchestrator — classify customer intake and route.

Single cross-platform entry for Slack Connect, internal customer channels,
Gmail ``Customer`` mail, and Discord community intake. Bugs →
``engineering/issue/`` + Linear; feature requests → product ledger + ranked
snapshot; discussions → open threads (Slack) or open-conversation tracker (Discord).

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
GENERAL_PRODUCT = "general"

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


@dataclass
class CommunityIntake:
    source: str = "discord"
    title: str = ""
    body: str = ""
    requester_handle: str = ""
    requester_id: str = ""
    permalink: str = ""
    channel_id: str = ""
    thread_id: str = ""
    message_id: str = ""
    parent_channel_id: str = ""
    category: str = ""
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

    def process(self, intake: CustomerIntake, *, community: bool = False) -> dict[str, Any]:
        if community:
            raise TypeError("use process_community() for CommunityIntake")
        category = classify_customer_intake(intake)
        crm_slug = self._record_crm(intake)
        if category == "bug":
            routed = self._route_bug(intake, community=False)
        elif category == "feature":
            routed = self._route_feature(intake, product_slug=GENERAL_PRODUCT)
        else:
            routed = self._route_discussion(intake)

        notified = self._notify(intake, category, routed)
        return {
            "category": category,
            "crm_slug": crm_slug,
            "notified": notified,
            **routed,
        }

    def process_community(self, intake: CommunityIntake) -> dict[str, Any]:
        from company_brain.agents.growth.discord.triage_heuristics import is_spam

        text = f"{intake.title}\n{intake.body}".strip()
        if is_spam(text):
            return {"category": "noise", "skipped": True, "reason": "spam"}

        category = intake.category or classify_customer_intake(
            CustomerIntake(source=intake.source, title=intake.title, body=intake.body)
        )
        if category == "bug":
            routed = self._route_bug(_community_as_customer(intake), community=True)
            notified = self._notify_community(intake, category, routed)
            return {"category": category, "notified": notified, **routed}

        if category == "feature":
            routed = self._route_community_feature(intake)
            notified = self._notify_community(intake, category, routed)
            return {"category": category, "notified": notified, **routed}

        routed = self._route_community_discussion(intake)
        return {"category": category, **routed}

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

    def _route_bug(self, intake: CustomerIntake, *, community: bool) -> dict[str, Any]:
        linear_issue: dict[str, Any] = {}
        if linear_client.linear_is_configured():
            try:
                bug_title = "Community bug report" if community else "Customer bug report"
                linear_issue = linear_client.create_issue(
                    title=intake.title[:200] or bug_title,
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
        body = _issue_page_body(intake, linear_issue, community=community)
        page_id = write_wiki_page(
            rel_path,
            intake.title[:120] or ("Community Issue" if community else "Customer Issue"),
            body,
            mode=UPDATE,
            section="engineering",
            type_="issue",
            extra_frontmatter={
                "origin": intake.source,
                "linear_id": linear_issue.get("identifier", ""),
                "linear_url": linear_issue.get("url", ""),
                "customer": not community,
            },
        )
        rebuild_issue_index()
        return {
            "wiki_path": rel_path,
            "linear_id": linear_issue.get("identifier", ""),
            "linear_url": linear_issue.get("url", ""),
            "notion_page_id": page_id,
        }

    def _route_feature(
        self,
        intake: CustomerIntake,
        *,
        product_slug: str = GENERAL_PRODUCT,
    ) -> dict[str, Any]:
        heading = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        section = format_append_section(
            heading,
            _feature_log_body(intake, product_slug=product_slug),
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

    def _route_community_feature(self, intake: CommunityIntake) -> dict[str, Any]:
        from company_brain.agents.growth.discord import discord_client
        from company_brain.agents.growth.discord.product_catalog import (
            draft_technical_reply,
            find_catalog_match,
            infer_product_slug,
            load_product_catalog,
        )
        from company_brain.agents.growth.discord.routing import DiscordRoutingStore
        from company_brain.agents.growth.shared.growth_slack import discord_review_notifier
        from company_brain.members_config import load_members_config

        catalog = load_product_catalog()
        text = f"{intake.title}\n{intake.body}"
        match = find_catalog_match(text, catalog)
        parent = intake.parent_channel_id or intake.channel_id
        team_ids = load_members_config().team_discord_ids()
        author_ids = discord_client.conversation_author_ids(parent, intake.thread_id)
        team_engaged = bool(team_ids & author_ids)

        store = DiscordRoutingStore()
        record = store.read(parent, intake.thread_id)
        if match:
            if team_engaged or (record and record.handled.get("discord_draft")):
                return {
                    "wiki_path": None,
                    "duplicate": True,
                    "draft_skipped": True,
                    "reason": "team_engaged_or_already_drafted",
                }
            draft = draft_technical_reply(
                title=intake.title,
                body=intake.body,
                match=match,
                permalink=intake.permalink,
            )
            lines = [
                "*Discord draft reply (human review)*",
                f"*Product:* {match.product_name}",
                f"*Match:* {match.matched_text} ({match.match_kind})",
                f"*Thread:* {intake.permalink or intake.thread_id}",
                "",
                draft,
            ]
            discord_review_notifier().emit(Signal(text="\n".join(lines), severity=ACTIONABLE))
            store.upsert(
                parent,
                intake.thread_id,
                kind="feature_pending",
                community=True,
                extracted={
                    **((record.extracted if record else {}) or {}),
                    "permalink": intake.permalink,
                    "title_preview": intake.title[:200],
                },
            )
            updated = store.read(parent, intake.thread_id)
            if updated:
                store.mark_handled(updated, "discord_draft")
            return {"duplicate": True, "draft_sent": True, "match_kind": match.match_kind}

        product_slug = infer_product_slug(intake.title, intake.body, catalog)
        customer = _community_as_customer(intake)
        return self._route_feature(customer, product_slug=product_slug)

    def _route_community_discussion(self, intake: CommunityIntake) -> dict[str, Any]:
        from company_brain.agents.growth.discord.routing import DiscordRoutingStore

        parent = intake.parent_channel_id or intake.channel_id
        store = DiscordRoutingStore()
        store.upsert(
            parent,
            intake.thread_id,
            parent_channel_id=parent,
            kind="discussion_open",
            attention="2. Reply",
            community=True,
            extracted={
                "message_id": intake.message_id,
                "channel_id": intake.channel_id,
                "permalink": intake.permalink,
                "author_handle": intake.requester_handle,
                "author_id": intake.requester_id,
                "title_preview": intake.title[:200],
                "category": intake.category or "discussion",
            },
        )
        return {"open_conversation": True}

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

    def _notify_community(
        self,
        intake: CommunityIntake,
        category: str,
        routed: dict[str, Any],
    ) -> bool:
        if routed.get("draft_sent") or routed.get("draft_skipped"):
            return bool(routed.get("draft_sent"))
        from company_brain.agents.growth.shared.growth_slack import growth_notifier

        lines = [
            f"*Community {category}* (discord)",
            f"*{intake.title}*",
        ]
        if intake.requester_handle:
            lines.append(f"*From:* {intake.requester_handle}")
        if intake.permalink:
            lines.append(f"*Link:* {intake.permalink}")
        if routed.get("linear_url"):
            lines.append(f"*Linear:* {routed['linear_url']}")
        if routed.get("wiki_path"):
            lines.append(f"*Wiki:* `{routed['wiki_path']}`")
        preview = (intake.body or "").strip()[:400]
        if preview:
            lines.extend(["", preview])
        return growth_notifier().emit(Signal(text="\n".join(lines), severity=ACTIONABLE))

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
    """Parse the feature request log and return a ranked snapshot by product section."""
    from company_brain.agents.growth.discord.product_catalog import (
        GENERAL_SLUG,
        load_product_catalog,
    )
    from company_brain.wiki.publish import read_wiki_page

    catalog = load_product_catalog()
    try:
        log = read_wiki_page(FEATURE_REQUEST_LOG)
    except FileNotFoundError:
        log = ""

    sections: dict[str, dict[str, tuple[int, str]]] = {}
    for block in re.split(r"\n## ", log):
        if not block.strip():
            continue
        title_match = re.search(r"\*\*Title:\*\*\s*(.+)", block)
        if not title_match:
            continue
        title = title_match.group(1).strip()
        product_match = re.search(r"\*\*Product:\*\*\s*(.+)", block)
        product_slug = product_match.group(1).strip().lower() if product_match else GENERAL_SLUG
        section_name = catalog.display_name(product_slug)
        bucket = sections.setdefault(section_name, {})
        key = title.lower()
        count, _ = bucket.get(key, (0, title))
        bucket[key] = (count + 1, title)

    lines = ["# Feature Requests", "", "Ranked by repeat mentions in the request log.", ""]
    if not sections:
        lines.append("_No feature requests yet._\n")
        return "\n".join(lines)

    ordered_names = sorted(sections.keys(), key=lambda n: (n != "General", n.lower()))
    for section_name in ordered_names:
        bucket = sections[section_name]
        ranked = sorted(bucket.items(), key=lambda kv: (-kv[1][0], kv[0]))
        lines.extend([f"## {section_name}", ""])
        if not ranked:
            lines.append("_No requests._\n")
            continue
        lines.append("| Rank | Requests | Title |")
        lines.append("| --- | --- | --- |")
        for idx, (_key, (count, title)) in enumerate(ranked[:50], start=1):
            lines.append(f"| {idx} | {count} | {title} |")
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


def _issue_page_body(
    intake: CustomerIntake,
    linear_issue: dict[str, Any],
    *,
    community: bool = False,
) -> str:
    lines = [
        f"# {intake.title}",
        "",
        f"**Origin:** {intake.source}",
        "**Category:** bug",
    ]
    if community:
        lines.append("**Community:** true")
    if linear_issue.get("url"):
        lines.append(f"**Linear:** [{linear_issue.get('identifier')}]({linear_issue['url']})")
    if intake.permalink:
        lines.append(f"**Source:** {intake.permalink}")
    lines.extend(["", "## Description", "", intake.body or "_No details provided._", ""])
    return "\n".join(lines)


def _feature_log_body(intake: CustomerIntake, *, product_slug: str = GENERAL_PRODUCT) -> str:
    lines = [
        f"**Title:** {intake.title}",
        f"**Source:** {intake.source}",
        f"**Product:** {product_slug}",
    ]
    if intake.requester_name or intake.requester_email:
        who = intake.requester_name or display_name_from_from_header(intake.requester_email)
        lines.append(f"**Requester:** {who}")
    if intake.permalink:
        lines.append(f"**Link:** {intake.permalink}")
    lines.extend(["", intake.body[:2000] if intake.body else ""])
    return "\n".join(lines)


def _community_as_customer(intake: CommunityIntake) -> CustomerIntake:
    return CustomerIntake(
        source=intake.source,
        title=intake.title,
        body=intake.body,
        requester_name=intake.requester_handle,
        permalink=intake.permalink,
        channel=intake.channel_id,
        thread_ts=intake.thread_id,
        message_ts=intake.message_id,
    )


class CustomerSupportAgent(BaseAgent):
    """Cross-platform customer support orchestrator."""

    name = "customer_support"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._orchestrator = CustomerSupportOrchestrator()

    def run(
        self,
        *,
        intake: CustomerIntake | CommunityIntake | None = None,
        community: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if intake is None:
            return {"status": "skipped", "reason": "no_intake"}
        if isinstance(intake, CommunityIntake) or community:
            if not isinstance(intake, CommunityIntake):
                return {"status": "skipped", "reason": "community_intake_required"}
            return self._orchestrator.process_community(intake)
        return self._orchestrator.process(intake)
