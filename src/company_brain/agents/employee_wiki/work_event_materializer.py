"""Work Event Materializer — ledger entries → employee wiki pages.

Deterministic templates (no LLM). Materializes Linear, Granola, Gmail, and Slack
events into quarterly work_log + refreshes ``_index.md`` snapshot.

SDK: Neither (wiki writes only).
"""

from __future__ import annotations

import re
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.config import AppConfig
from company_brain.members_config import MembersConfig, load_members_config
from company_brain.wiki.employee_paths import member_index_path, member_work_log_path
from company_brain.wiki.employee_publish import APPEND, UPDATE, write_employee_wiki_page
from company_brain.wiki.work_events import WorkEvent, WorkEventStore, event_target_members

_BULLET_RE = re.compile(r"^-\s+(.+)$", re.M)


class WorkEventMaterializerAgent(BaseAgent):
    """Materialize a single work event into employee wiki pages."""

    name = "work_event_materializer"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._events = WorkEventStore()
        self._members = load_members_config()

    def run(
        self,
        *,
        event: WorkEvent | None = None,
        event_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if event is None and event_id:
            event = self._events.get(event_id)
        if event is None:
            return {"status": "skipped", "reason": "no_event"}

        targets = event_target_members(event)
        if not targets:
            return {"status": "skipped", "reason": "unassigned"}

        materialized: list[str] = []
        skipped: list[str] = []
        paths: list[str] = []

        for member in targets:
            if not _member_active(self._members, member):
                skipped.append(member)
                continue
            if not _ingest_allowed(self._members, member, event.source):
                skipped.append(member)
                continue
            if member in (event.materialized.get("employee") or []):
                skipped.append(member)
                continue

            if event.source == "linear":
                path = self._materialize_linear(event, member)
            elif event.source == "granola":
                path = self._materialize_granola(event, member)
            elif event.source == "gmail":
                path = self._materialize_gmail(event, member)
            elif event.source == "slack":
                path = self._materialize_slack(event, member)
            else:
                return {"status": "skipped", "reason": f"unsupported_source:{event.source}"}

            self._events.mark_materialized(event.event_id, employee_member=member)
            _refresh_member_index(member)
            materialized.append(member)
            paths.append(path)

        if not materialized:
            return {"status": "skipped", "reason": "no_active_targets", "skipped": skipped}

        return {
            "status": "ok",
            "materialized": materialized,
            "paths": paths,
            "source": event.source,
            "skipped": skipped,
        }

    def _append_work_log(
        self,
        member: str,
        *,
        heading: str,
        line: str,
        artifact_refs: list[str],
        company_links: list[str] | None = None,
    ) -> str:
        section = f"## {heading}\n\n{line}\n"
        rel = member_work_log_path(member)
        write_employee_wiki_page(
            rel,
            f"Work log — {rel.split('/')[-1].removesuffix('.md')}",
            section,
            member=member,
            mode=APPEND,
            artifact_refs=artifact_refs,
            company_links=company_links or [],
            mirror_notion=False,
        )
        return rel

    def _materialize_linear(self, event: WorkEvent, member: str) -> str:
        payload = event.payload or {}
        ident = payload.get("identifier") or event.artifact_ref.replace("linear:", "")
        title = payload.get("title") or ident
        status = payload.get("status") or ""
        url = payload.get("url") or ""
        line = f"- [{ident}]({url}) — {title}" if url else f"- **{ident}** — {title}"
        if status:
            line += f" ({status})"
        line += f" · `{event.artifact_ref}`"
        heading = f"{event.event_type.replace('_', ' ').title()} — {ident}"
        return self._append_work_log(
            member,
            heading=heading,
            line=line,
            artifact_refs=[event.artifact_ref],
            company_links=list(payload.get("company_links") or []),
        )

    def _materialize_granola(self, event: WorkEvent, member: str) -> str:
        payload = event.payload or {}
        title = payload.get("title") or "Meeting"
        meeting_date = payload.get("meeting_date") or ""
        action_count = int(payload.get("action_item_count") or 0)
        role = "contributor" if member != event.primary_member else "primary"
        line = f"- Meeting **{title}** ({meeting_date}) · `{event.artifact_ref}`"
        if action_count:
            line += f" — {action_count} action item(s)"
        if role == "contributor":
            line += " _(contributor)_"
        heading = f"Meeting — {title}"
        return self._append_work_log(
            member,
            heading=heading,
            line=line,
            artifact_refs=[event.artifact_ref],
            company_links=list(payload.get("company_links") or []),
        )

    def _materialize_gmail(self, event: WorkEvent, member: str) -> str:
        payload = event.payload or {}
        subject = payload.get("subject") or "Gmail item"
        task_class = payload.get("task_class") or "inbox_action"
        url = payload.get("url") or ""
        ident = payload.get("linear_identifier") or ""
        line = f"- **{subject}**"
        if ident:
            line = f"- [{ident}]({url}) — {subject}" if url else f"- **{ident}** — {subject}"
        elif url:
            line = f"- [{subject}]({url})"
        line += f" · Gmail `{task_class}` · `{event.artifact_ref}`"
        heading = f"Gmail — {subject[:80]}"
        return self._append_work_log(
            member,
            heading=heading,
            line=line,
            artifact_refs=[event.artifact_ref],
            company_links=list(payload.get("company_links") or []),
        )

    def _materialize_slack(self, event: WorkEvent, member: str) -> str:
        payload = event.payload or {}
        title = payload.get("title") or "Slack action item"
        channel = payload.get("channel") or ""
        line = f"- {title} · Slack `{channel}` · `{event.artifact_ref}`"
        heading = f"Slack — {title[:80]}"
        return self._append_work_log(
            member,
            heading=heading,
            line=line,
            artifact_refs=[event.artifact_ref],
        )


def _member_active(cfg: MembersConfig, member: str) -> bool:
    spec = cfg.get(member)
    return spec is not None and spec.is_active


def _ingest_allowed(cfg: MembersConfig, member: str, source: str) -> bool:
    spec = cfg.get(member)
    if spec is None:
        return False
    ingest = spec.ingest
    if source == "granola":
        return (ingest.granola or "full").lower() != "off"
    if source == "gmail":
        return (ingest.gmail or "work_related").lower() != "off"
    if source == "slack":
        return (ingest.slack or "watched_channels_only").lower() != "off"
    return True


def _refresh_member_index(member: str) -> None:
    """Refresh ``_index.md`` ## This quarter from recent work_log bullets."""
    from company_brain.wiki.employee_store import employee_wiki_store

    store = employee_wiki_store()
    wl_rel = member_work_log_path(member)
    bullets = _recent_work_log_bullets(store, wl_rel, limit=8)
    index_rel = member_index_path(member)
    if not store.exists(index_rel):
        return

    body = store.read(index_rel).body
    quarter_block = "## This quarter\n\n"
    if bullets:
        quarter_block += "\n".join(f"- {b}" for b in bullets) + "\n"
    else:
        quarter_block += "_See work_log for detailed entries._\n"

    updated = _replace_section(body, "This quarter", quarter_block.strip())
    write_employee_wiki_page(
        index_rel,
        store.read(index_rel).frontmatter.get("title") or "Current work",
        updated,
        member=member,
        mode=UPDATE,
        store=store,
        mirror_notion=False,
    )


def _recent_work_log_bullets(store, wl_rel: str, *, limit: int) -> list[str]:
    if not store.exists(wl_rel):
        return []
    body = store.read(wl_rel).body
    bullets: list[str] = []
    for match in _BULLET_RE.finditer(body):
        text = match.group(1).strip()
        if text and text not in bullets:
            bullets.append(text)
    return bullets[-limit:]


def _replace_section(body: str, section_title: str, new_section: str) -> str:
    marker = f"## {section_title}"
    if marker not in body:
        return body.rstrip() + "\n\n" + new_section + "\n"
    before, rest = body.split(marker, 1)
    after_parts = rest.split("\n## ", 1)
    tail = f"\n## {after_parts[1]}" if len(after_parts) > 1 else ""
    return before.rstrip() + "\n\n" + new_section + tail


def record_linear_work_event(
    *,
    primary_member: str,
    issue_id: str,
    identifier: str,
    title: str,
    status: str,
    url: str = "",
    event_type: str = "linear_status_change",
    contributors: list[str] | None = None,
    company_links: list[str] | None = None,
    store: WorkEventStore | None = None,
) -> WorkEvent:
    """Append a Linear work event to the ledger (idempotent on artifact_ref + event_type)."""
    store = store or WorkEventStore()
    artifact_ref = f"linear:{identifier or issue_id}"
    existing = store.find_by_artifact(artifact_ref)
    if existing and existing.event_type == event_type and existing.payload.get("status") == status:
        return existing

    event = WorkEvent.create(
        source="linear",
        artifact_ref=artifact_ref,
        primary_member=primary_member,
        event_type=event_type,
        payload={
            "issue_id": issue_id,
            "identifier": identifier,
            "title": title,
            "status": status,
            "url": url,
            "company_links": list(company_links or []),
        },
        contributors=contributors,
    )
    return store.append(event)


def record_granola_work_event(
    *,
    note_id: str,
    meeting_date: str,
    title: str,
    member_label: str | None = None,
    detail: dict[str, Any] | None = None,
    action_item_count: int = 0,
    company_links: list[str] | None = None,
    store: WorkEventStore | None = None,
    members: MembersConfig | None = None,
) -> WorkEvent | None:
    """Record a Granola meeting ingest event (primary + contributor members)."""
    members = members or load_members_config()
    primary = members.find_by_granola_label(member_label or "") if member_label else None
    if not primary:
        owner = (detail or {}).get("owner") or {}
        primary = members.find_by_gmail_mailbox(str(owner.get("email") or ""))
    if not primary:
        return None

    contributors = _granola_contributors(detail or {}, members, exclude=primary)
    store = store or WorkEventStore()
    artifact_ref = f"granola:{note_id}"
    existing = store.find_by_artifact(artifact_ref)
    if existing and existing.event_type == "meeting_ingested":
        return existing

    event = WorkEvent.create(
        source="granola",
        artifact_ref=artifact_ref,
        primary_member=primary,
        event_type="meeting_ingested",
        payload={
            "note_id": note_id,
            "title": title,
            "meeting_date": meeting_date,
            "action_item_count": action_item_count,
            "company_links": list(company_links or []),
        },
        contributors=contributors,
    )
    return store.append(event)


def record_gmail_work_event(
    *,
    primary_member: str,
    message_id: str,
    subject: str,
    task_class: str,
    linear_identifier: str = "",
    url: str = "",
    company_links: list[str] | None = None,
    store: WorkEventStore | None = None,
) -> WorkEvent | None:
    """Record a Gmail task binding as a work event."""
    if not primary_member:
        return None
    store = store or WorkEventStore()
    artifact_ref = f"gmail:{message_id}"
    existing = store.find_by_artifact(artifact_ref)
    if existing and existing.event_type == "gmail_task_created":
        return existing

    event = WorkEvent.create(
        source="gmail",
        artifact_ref=artifact_ref,
        primary_member=primary_member,
        event_type="gmail_task_created",
        payload={
            "message_id": message_id,
            "subject": subject,
            "task_class": task_class,
            "linear_identifier": linear_identifier,
            "url": url,
            "company_links": list(company_links or []),
        },
    )
    return store.append(event)


def record_slack_work_event(
    *,
    primary_member: str,
    channel: str,
    thread_ts: str,
    title: str,
    store: WorkEventStore | None = None,
) -> WorkEvent | None:
    """Record a Slack action-item thread (importance gate already passed)."""
    if not primary_member:
        return None
    store = store or WorkEventStore()
    artifact_ref = f"slack:{channel}:{thread_ts}"
    existing = store.find_by_artifact(artifact_ref)
    if existing and existing.event_type == "slack_action_item":
        return existing

    event = WorkEvent.create(
        source="slack",
        artifact_ref=artifact_ref,
        primary_member=primary_member,
        event_type="slack_action_item",
        payload={
            "channel": channel,
            "thread_ts": thread_ts,
            "title": title,
        },
    )
    return store.append(event)


def _granola_contributors(
    detail: dict[str, Any],
    members: MembersConfig,
    *,
    exclude: str,
) -> list[str]:
    found: list[str] = []
    for person in detail.get("attendees") or []:
        email = ""
        if isinstance(person, dict):
            email = str(person.get("email") or "")
        key = members.find_by_gmail_mailbox(email) if email else None
        if key and key != exclude and key not in found:
            found.append(key)
    return found
