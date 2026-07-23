"""@wiki slash-style commands (threads, help, growth allow-list)."""

from __future__ import annotations

import re
from typing import Any

from company_brain.agents.operations.slack.open_threads import open_threads_for_member
from company_brain.agents.operations.slack.routing import SlackRoutingStore
from company_brain.agents.operations.slack.wiki_acl import ask_wiki_allowed
from company_brain.members_config import load_members_config

# First tokens that enter the command layer (not AskWiki Q&A).
COMMAND_PREFIXES = frozenset(
    {
        "help",
        "?",
        "threads",
        "sync",
        "register",
        "plan",
        "partner",
        "partnership",
        "draft",
        "research",
        "wrap",
    }
)


def handle_wiki_command(
    *,
    channel_id: str,
    thread_ts: str,
    command: str,
    slack_user_id: str,
    text: str = "",
) -> dict[str, Any]:
    if not ask_wiki_allowed(channel_id):
        return _reply(
            channel_id,
            thread_ts,
            "`@wiki` commands are not available in Connect channels.",
        )

    raw = (text or command or "").strip()
    cmd = raw.lower()
    first = cmd.split(None, 1)[0] if cmd else ""

    if first in {"help", "?"}:
        return _reply(channel_id, thread_ts, _help_text())

    if first in {"threads", "open-threads"} or cmd in {"open threads"}:
        return _list_threads(channel_id, thread_ts, slack_user_id)

    if first == "sync":
        return _sync_now(channel_id, thread_ts, raw)

    if first not in COMMAND_PREFIXES:
        return {"status": "not_command"}

    try:
        result = _dispatch_growth_command(raw)
    except Exception as exc:
        return _reply(channel_id, thread_ts, f"Command failed: {exc}")

    if result.get("status") == "not_command":
        return result
    return _reply(channel_id, thread_ts, result.get("message") or str(result))


def _help_text() -> str:
    return (
        "*@wiki commands*\n"
        "• `@wiki <question>` — search the wiki (scoped to this channel)\n"
        "• `@wiki sync now <platform>` — kick sync (notion, crm, github, posthog)\n"
        "• `@wiki threads` — your open Slack threads\n"
        "• `@wiki register event <name> [on YYYY-MM-DD]` — register a company event\n"
        "• `@wiki plan event <slug>` — assisted planning doc\n"
        "• `@wiki partner one-pager <event-slug> for <partner>` — partnership brief\n"
        "• `@wiki wrap event <slug>` — post-event wrap + queues\n"
        "• `@wiki draft <blog|x|linkedin> <instructions>` — content draft (never posts)\n"
        "• `@wiki research leads from event <slug>` — queue attendee lead research "
        "(CSV via CLI if needed)\n"
        "• `@wiki help` — this message"
    )


def _sync_now(channel_id: str, thread_ts: str, raw: str) -> dict[str, Any]:
    from company_brain.wiki.platform_sync import sync_platform

    parts = raw.split()
    # sync now notion | sync notion
    platform = ""
    if len(parts) >= 3 and parts[1].lower() == "now":
        platform = parts[2]
    elif len(parts) >= 2:
        platform = parts[1]
    if not platform:
        return _reply(
            channel_id,
            thread_ts,
            "Usage: `@wiki sync now <platform>` (notion, crm, github, posthog).",
        )
    result = sync_platform(platform)
    if result.get("status") == "ok":
        return _reply(
            channel_id,
            thread_ts,
            f"Sync kicked for *{result.get('platform')}*: `{result.get('result')}`",
        )
    return _reply(
        channel_id,
        thread_ts,
        f"Sync failed: {result.get('reason')}. Supported: {result.get('supported')}",
    )


def _dispatch_growth_command(raw: str) -> dict[str, Any]:
    from company_brain.config import load_config
    from company_brain.runtime import get_runtime

    text = raw.strip()
    lower = text.lower()
    config = load_config()
    runtime = get_runtime()

    m = re.match(
        r"register\s+event\s+(.+?)(?:\s+on\s+(\d{4}-\d{2}-\d{2}))?$",
        text,
        re.I,
    )
    if m:
        from company_brain.agents.growth.activity.event_register import EventRegisterAgent

        name = m.group(1).strip().strip("\"'")
        date = (m.group(2) or "").strip()
        out = runtime.run(
            EventRegisterAgent,
            config,
            name=name,
            date=date,
            notes="Registered from Slack @wiki\n\nThread context may follow.",
            source="slack",
            notify=False,
        )
        return {
            "status": "ok",
            "message": f"Event registered: `{out.get('slug')}` → `{out.get('wiki_path')}`",
        }

    m = re.match(r"plan\s+event\s+([a-z0-9-]+)\s*$", lower)
    if m:
        from company_brain.agents.growth.activity.event_plan import EventPlanAgent

        slug = m.group(1)
        out = runtime.run(EventPlanAgent, config, slug=slug)
        return {
            "status": "ok",
            "message": f"Planning updated for `{slug}` ({out.get('status')})",
        }

    m = re.match(
        r"(?:partner(?:ship)?\s+one[- ]pager|partner\s+brief)\s+([a-z0-9-]+)\s+for\s+(.+)$",
        text,
        re.I,
    )
    if m:
        from company_brain.agents.growth.activity.partnership_brief import PartnershipBriefAgent

        slug = m.group(1).lower()
        partner = m.group(2).strip().strip("\"'")
        out = runtime.run(
            PartnershipBriefAgent,
            config,
            slug=slug,
            partner_name=partner,
        )
        return {
            "status": "ok",
            "message": f"Partner brief: `{out.get('wiki_path')}`",
        }

    m = re.match(r"wrap\s+event\s+([a-z0-9-]+)\s*$", lower)
    if m:
        from company_brain.agents.growth.activity.event_wrap import EventWrapAgent

        slug = m.group(1)
        out = runtime.run(EventWrapAgent, config, slug=slug, notify=False)
        return {
            "status": "ok",
            "message": f"Event wrap done for `{slug}` ({out.get('status')})",
        }

    m = re.match(r"draft\s+(blog|x|linkedin)\s+(.+)$", text, re.I)
    if m:
        from company_brain.agents.growth.content.draft_writer import DraftWriterAgent

        channel = m.group(1).lower()
        instructions = m.group(2).strip()
        out = runtime.run(
            DraftWriterAgent,
            config,
            channel=channel,
            instructions=instructions,
        )
        return {
            "status": "ok",
            "message": f"Draft ready: `{out.get('wiki_path')}` (never posted)",
        }

    m = re.match(r"research\s+leads?\s+from\s+event\s+([a-z0-9-]+)\s*$", lower)
    if m:
        from company_brain.agents.growth.leads.queue import enqueue_lead_job

        slug = m.group(1)
        job = enqueue_lead_job(
            source="attendee_csv",
            label=f"event:{slug}",
            payload={
                "csv_text": "",
                "event_slug": slug,
                "note": "Upload CSV via `company-brain growth leads enqueue` with file",
            },
        )
        return {
            "status": "ok",
            "message": (
                f"Lead job `{job['id']}` queued for event `{slug}`. "
                "Add attendee CSV via CLI when ready."
            ),
        }

    return {"status": "not_command"}


def _list_threads(channel_id: str, thread_ts: str, slack_user_id: str) -> dict[str, Any]:
    members = load_members_config()
    member_key = members.find_by_slack_user_id(slack_user_id)
    if not member_key:
        return _reply(
            channel_id,
            thread_ts,
            "No member binding for your Slack user — open threads are unavailable.",
        )

    open_records = list(SlackRoutingStore().iter_open())
    mine = open_threads_for_member(member_key, open_records)
    if not mine:
        return _reply(channel_id, thread_ts, "You have no open threads right now.")

    lines = [f"*Open threads for {member_key}*", ""]
    for rec in mine[:15]:
        link = (rec.extracted or {}).get("permalink") or f"{rec.channel}:{rec.thread_ts}"
        kind = rec.kind or "thread"
        lines.append(f"• {kind} — {link}")
    return _reply(channel_id, thread_ts, "\n".join(lines))


def _reply(channel_id: str, thread_ts: str, text: str) -> dict[str, Any]:
    from company_brain.agents.operations.shared.operations_slack import reply_in_thread

    delivered, ts = reply_in_thread(channel_id, thread_ts, text)
    return {"status": "replied" if delivered else "suppressed", "ts": ts}
