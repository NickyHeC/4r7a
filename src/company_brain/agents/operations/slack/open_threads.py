"""Open thread helpers — reactions, employee wiki pages."""

from __future__ import annotations

from typing import Any

from company_brain.agents.operations.slack import channels_config, slack_client
from company_brain.agents.operations.slack import slack_config as cfg
from company_brain.agents.operations.slack.routing import SlackRoutingRecord, SlackRoutingStore
from company_brain.members_config import load_members_config
from company_brain.wiki.employee_publish import UPDATE, write_employee_wiki_page

OPEN_THREAD_REL = "open-thread.md"
OPEN_THREAD_TITLE = "Open Threads"


def is_ack_reaction(name: str) -> bool:
    return name in cfg.reaction_names("acknowledge")


def is_done_reaction(name: str) -> bool:
    return name in cfg.reaction_names("done")


def handle_reaction_added(
    *,
    channel_id: str,
    thread_ts: str,
    reaction: str,
    user_id: str,
    routing: SlackRoutingStore | None = None,
) -> dict[str, Any]:
    store = routing or SlackRoutingStore()
    channel = slack_client.channel_label(channel_id, name=channels_config.channel_name(channel_id))
    record = store.read(channel, thread_ts)
    if not record:
        return {"status": "skipped", "reason": "no_routing_record"}

    if is_ack_reaction(reaction):
        record.handled["read_reaction"] = reaction
        record.handled["acknowledged_by"] = user_id
        store.write(record)
        _refresh_assignee_pages(store)
        return {"status": "acknowledged", "reaction": reaction}

    if is_done_reaction(reaction):
        record.handled["closed"] = reaction
        record.handled["closed_by"] = user_id
        store.write(record)
        _refresh_assignee_pages(store)
        return {"status": "closed", "reaction": reaction}

    return {"status": "ignored", "reaction": reaction}


def open_threads_for_member(
    member_key: str,
    records: list[SlackRoutingRecord],
) -> list[SlackRoutingRecord]:
    spec = load_members_config().get(member_key)
    if not spec:
        return []
    slack_id = spec.bindings.slack_user_id
    if not slack_id:
        return []
    out: list[SlackRoutingRecord] = []
    for record in records:
        if record.handled.get("closed"):
            continue
        if slack_id in record.assignees:
            out.append(record)
    return out


def render_open_threads_body(records: list[SlackRoutingRecord]) -> str:
    if not records:
        return "_No open threads._\n"

    lines = ["| Attention | Kind | Channel | Thread | Preview |", "| --- | --- | --- | --- | --- |"]
    for record in sorted(records, key=lambda r: r.updated_at, reverse=True):
        preview = str((record.extracted or {}).get("text_preview") or "")[:120]
        link = str((record.extracted or {}).get("permalink") or record.thread_ts)
        lines.append(
            f"| {record.attention or '—'} | {record.kind or '—'} | "
            f"{record.channel} | {link} | {preview} |"
        )
    return "\n".join(lines) + "\n"


def write_member_open_thread_page(
    member_key: str,
    records: list[SlackRoutingRecord],
) -> str | None:
    body = render_open_threads_body(records)
    rel = f"{member_key}/{OPEN_THREAD_REL}"
    return write_employee_wiki_page(
        rel,
        OPEN_THREAD_TITLE,
        f"# {OPEN_THREAD_TITLE}\n\n{body}",
        member=member_key,
        mode=UPDATE,
        sync="private",
    )


def _refresh_assignee_pages(store: SlackRoutingStore) -> None:
    open_records = list(store.iter_open())
    OpenThreadMonitorAgent = _monitor_cls()
    OpenThreadMonitorAgent.enrich_permalinks(open_records)
    for member_key in load_members_config().active_members():
        member_records = open_threads_for_member(member_key, open_records)
        write_member_open_thread_page(member_key, member_records)


def _monitor_cls() -> type:
    from company_brain.agents.operations.slack.open_thread_monitor import OpenThreadMonitorAgent

    return OpenThreadMonitorAgent
