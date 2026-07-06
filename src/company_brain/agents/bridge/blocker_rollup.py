"""Blocker Rollup — daily company/engineering priority snapshot.

SDK: Neither (deterministic templating only — no LLM summarization).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.result import AgentResult
from company_brain.bridge.config import load_bridge_config
from company_brain.bridge.events import BridgeEventStore
from company_brain.config import resolve_employee_wiki_dir
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import MarkdownDoc


class BlockerRollupAgent(BaseAgent):
    name = "blocker_rollup"
    WRITE_MODE = UPDATE

    def run(self, **kwargs: Any) -> dict[str, Any]:
        cfg = load_bridge_config()
        rows = self._collect_active_blockers()
        lead_body = self._read_lead_focus(cfg.rollup.lead_focus_path)
        body = self._render_rollup(rows, lead_body)
        write_wiki_page(
            cfg.rollup.blockers_path,
            "Engineering Blockers",
            body,
            mode=UPDATE,
            section="engineering",
            sync_label=cfg.rollup.blockers_sync,
        )
        return {"status": "ok", "blockers": len(rows), "path": cfg.rollup.blockers_path}

    def _collect_active_blockers(self) -> list[dict[str, str]]:
        root = resolve_employee_wiki_dir()
        seen: set[str] = set()
        rows: list[dict[str, str]] = []

        # Prefer materialized employee wiki pages.
        if root.exists():
            for path in sorted(root.glob("*/blockers/*.md")):
                member = path.relative_to(root).parts[0]
                rel = path.relative_to(root).as_posix()
                doc = self._read_employee(rel)
                if not doc:
                    continue
                fm = doc.frontmatter or {}
                if str(fm.get("status") or "active") != "active":
                    continue
                title = str(fm.get("title") or path.stem)
                dedupe = f"{member}:{title}:{fm.get('area', '')}"
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                rows.append(
                    {
                        "member": member,
                        "title": title,
                        "area": str(fm.get("area") or ""),
                        "severity": str(fm.get("severity") or ""),
                        "event_id": str(fm.get("event_id") or ""),
                    }
                )

        # Include unmaterialized ledger events not yet on disk.
        for event in BridgeEventStore().list_unmaterialized():
            if event.event_type != "blocker":
                continue
            dedupe = f"{event.member}:{event.payload.get('title')}:{event.payload.get('area')}"
            if dedupe in seen:
                continue
            seen.add(dedupe)
            rows.append(
                {
                    "member": event.member,
                    "title": str(event.payload.get("title") or ""),
                    "area": str(event.payload.get("area") or ""),
                    "severity": str(event.payload.get("severity") or ""),
                    "event_id": event.event_id,
                }
            )
        return rows

    def _read_employee(self, rel: str) -> MarkdownDoc | None:
        from company_brain.wiki.employee_store import LocalEmployeeWikiStore

        store = LocalEmployeeWikiStore()
        if not store.exists(rel):
            return None
        return store.read(rel)

    def _read_lead_focus(self, rel_path: str) -> str:
        from company_brain.wiki.publish import read_wiki_page

        return read_wiki_page(rel_path)

    def _render_rollup(self, rows: list[dict[str, str]], lead_body: str) -> str:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"_Updated {now}_",
            "",
            "## Lead focus (from master table)",
            "",
            lead_body.strip() if lead_body.strip() else "_No lead focus page yet._",
            "",
            "## Active blockers",
            "",
            "| Member | Severity | Area | Title |",
            "|--------|----------|------|-------|",
        ]
        if not rows:
            lines.append("| — | — | — | _No active blockers._ |")
        else:
            for row in sorted(rows, key=lambda r: (r.get("severity", ""), r.get("title", ""))):
                lines.append(
                    f"| {row['member']} | {row['severity']} | {row['area']} | {row['title']} |"
                )
        lines.append("")
        return "\n".join(lines)

    def verify(self, output: Any, **kwargs: Any) -> AgentResult:
        if output.get("status") == "ok":
            return AgentResult(output=output, status="ok")
        return AgentResult(output=output, status="rework", gaps=["rollup failed"])
