"""Bridge Event Materializer — ledger rows to employee wiki blocker pages.

SDK: Neither (deterministic).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.result import AgentResult
from company_brain.bridge.events import BridgeEvent, BridgeEventStore
from company_brain.wiki.employee_publish import write_employee_wiki_page
from company_brain.wiki.employee_store import employee_wiki_store
from company_brain.wiki.store import MarkdownDoc


class BridgeEventMaterializerAgent(BaseAgent):
    name = "bridge_event_materializer"
    max_iterations = 1

    def run(self, *, event: BridgeEvent | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        if isinstance(event, dict):
            event = BridgeEvent.from_dict(event)
        store = BridgeEventStore()
        if event.materialized:
            return {"status": "ok", "skipped": True, "event_id": event.event_id}

        payload = event.payload
        rel = f"{event.member}/blockers/{event.event_id}.md"
        title = str(payload.get("title") or "Blocker")
        body = "\n".join(
            [
                f"- **Area:** {payload.get('area', '')}",
                f"- **Severity:** {payload.get('severity', '')}",
                f"- **Blocked since:** {payload.get('blocked_since') or '—'}",
                f"- **Suggested owner:** {payload.get('suggested_owner') or '—'}",
                "",
                "### Evidence",
                "",
                str(payload.get("evidence") or "—"),
                "",
            ]
        )
        write_employee_wiki_page(
            rel,
            title,
            body,
            member=event.member,
            sync="private",
        )
        store_fs = employee_wiki_store()
        doc = store_fs.read(rel)
        fm = dict(doc.frontmatter or {})
        fm.update(
            {
                "status": "active",
                "event_id": event.event_id,
                "area": payload.get("area"),
                "severity": payload.get("severity"),
            }
        )
        store_fs.write(rel, MarkdownDoc(frontmatter=fm, body=doc.body))
        store.mark_materialized(event.event_id)
        return {"status": "ok", "event_id": event.event_id, "path": rel}

    def verify(self, output: Any, **kwargs: Any) -> AgentResult:
        if output.get("status") == "ok":
            return AgentResult(output=output, status="ok")
        return AgentResult(output=output, status="rework", gaps=["materialize failed"])
