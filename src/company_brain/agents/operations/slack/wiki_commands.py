"""@wiki slash-style commands (threads, help)."""

from __future__ import annotations

from typing import Any

from company_brain.agents.operations.slack import slack_client
from company_brain.agents.operations.slack.open_threads import open_threads_for_member
from company_brain.agents.operations.slack.routing import SlackRoutingStore
from company_brain.agents.operations.slack.wiki_acl import ask_wiki_allowed
from company_brain.members_config import load_members_config


def handle_wiki_command(
    *,
    channel_id: str,
    thread_ts: str,
    command: str,
    slack_user_id: str,
) -> dict[str, Any]:
    if not ask_wiki_allowed(channel_id):
        return _reply(
            channel_id,
            thread_ts,
            "`@wiki` commands are not available in Connect channels.",
        )

    cmd = (command or "").strip().lower()
    if cmd in {"help", "?"}:
        return _reply(
            channel_id,
            thread_ts,
            (
                "*@wiki commands*\n"
                "• `@wiki <question>` — search the wiki (scoped to this channel)\n"
                "• `@wiki threads` — your open Slack threads\n"
                "• `@wiki help` — this message"
            ),
        )

    if cmd in {"threads", "open-threads", "open threads"}:
        return _list_threads(channel_id, thread_ts, slack_user_id)

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
    try:
        ts = slack_client.post_thread_reply(channel_id, thread_ts, text)
        return {"status": "replied", "ts": ts}
    except slack_client.SlackClientError as exc:
        return {"status": "error", "reason": str(exc)}
