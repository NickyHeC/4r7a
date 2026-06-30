"""Work Event Materializer — ledger entries → employee wiki pages.

Deterministic templates (no LLM). Phase B: Linear task events → quarterly work_log.

SDK: Neither (wiki writes only).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.config import AppConfig
from company_brain.members_config import load_members_config
from company_brain.wiki.employee_paths import member_work_log_path
from company_brain.wiki.employee_publish import APPEND, write_employee_wiki_page
from company_brain.wiki.work_events import WorkEvent, WorkEventStore


class WorkEventMaterializerAgent(BaseAgent):
    """Materialize a single work event into employee (and later company) wiki pages."""

    name = "work_event_materializer"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._events = WorkEventStore()
        self._members = load_members_config()

    def run(self, *, event: WorkEvent | None = None, event_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        if event is None and event_id:
            event = self._events.get(event_id)
        if event is None:
            return {"status": "skipped", "reason": "no_event"}

        member = event.primary_member
        if not member or member == "unassigned":
            return {"status": "skipped", "reason": "unassigned"}

        spec = self._members.get(member)
        if spec is None or not spec.is_active:
            return {"status": "skipped", "reason": "unknown_or_inactive_member"}

        if event.source == "linear":
            result = self._materialize_linear(event)
        else:
            return {"status": "skipped", "reason": f"unsupported_source:{event.source}"}

        self._events.mark_materialized(event.event_id, employee_member=member)
        return result

    def _materialize_linear(self, event: WorkEvent) -> dict[str, Any]:
        member = event.primary_member
        payload = event.payload or {}
        ident = payload.get("identifier") or event.artifact_ref.replace("linear:", "")
        title = payload.get("title") or ident
        status = payload.get("status") or ""
        url = payload.get("url") or ""
        line = f"- [{ident}]({url}) — {title}" if url else f"- **{ident}** — {title}"
        if status:
            line += f" ({status})"
        line += f" · `{event.artifact_ref}`"

        section = f"## {event.event_type.replace('_', ' ').title()} — {ident}\n\n{line}\n"
        rel = member_work_log_path(member)
        write_employee_wiki_page(
            rel,
            f"Work log — {rel.split('/')[-1].removesuffix('.md')}",
            section,
            member=member,
            mode=APPEND,
            artifact_refs=[event.artifact_ref],
            company_links=list(payload.get("company_links") or []),
        )
        return {"status": "ok", "member": member, "path": rel, "source": "linear"}


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
        },
        contributors=contributors,
    )
    return store.append(event)
