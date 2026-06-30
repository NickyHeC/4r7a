"""Stale Audit Agent — weekly report of stale Linear projects and issues.

Writes ``engineering/linear/stale-audit.md`` and dispatches
``request_manual_management`` when proposals need human input.

SDK: Neither (deterministic heuristics).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.linear import linear_client
from company_brain.agents.engineering.linear.task_bindings import TaskBindingStore
from company_brain.agents.engineering.shared.linear_config import stale_audit_cfg, team_id, team_key
from company_brain.config import AppConfig
from company_brain.wiki.publish import write_wiki_page

REPORT_PATH = "engineering/linear/stale-audit.md"
REPORT_TITLE = "Stale Audit"


class StaleAuditAgent(BaseAgent):
    """Detect stale open issues and propose status updates for human review."""

    name = "linear_stale_audit"
    WRITE_MODE = "update"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._bindings = TaskBindingStore()
        self._cfg = stale_audit_cfg()

    def should_run(self, **kwargs: Any) -> bool:
        return linear_client.linear_is_configured()

    def run(
        self,
        *,
        dispatch_manual: bool = True,
        wait_for_completion: bool = False,
        sync: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        stale_days = int(self._cfg.get("stale_days") or 14)
        cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)

        issues = linear_client.list_open_issues(
            team_id=team_id() or None,
            team_key=team_key() or None,
            first=200,
        )
        proposals = self._build_proposals(issues, cutoff, stale_days)

        body = self._render_report(proposals, stale_days=stale_days)
        write_wiki_page(
            REPORT_PATH,
            REPORT_TITLE,
            body,
            mode="update",
            section="engineering/linear",
            sync=sync,
        )

        manual_status = None
        if dispatch_manual and proposals:
            from company_brain.agents.engineering.linear.request_manual_management import (
                RequestManualManagementAgent,
            )
            from company_brain.runtime import get_runtime

            manual_status = get_runtime().run(
                RequestManualManagementAgent,
                self.config,
                source_agent=self.name,
                proposals=proposals,
                context={"period": datetime.now(timezone.utc).strftime("%Y-%m-%d")},
                wait_for_completion=wait_for_completion,
                sync=sync,
            )

        return {
            "checked": len(issues),
            "proposals": len(proposals),
            "manual": manual_status,
        }

    def _build_proposals(
        self,
        issues: list[dict[str, Any]],
        cutoff: datetime,
        stale_days: int,
    ) -> list[dict[str, Any]]:
        proposals: list[dict[str, Any]] = []
        for issue in issues:
            updated_raw = issue.get("updatedAt") or ""
            try:
                updated = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if updated > cutoff:
                continue

            ident = issue.get("identifier") or issue.get("id") or "?"
            binding = self._bindings.find_by_linear(ident)
            suggested, reason = self._suggest_status(binding, updated, stale_days)
            proposals.append({
                "identifier": ident,
                "title": issue.get("title") or "",
                "current_status": (issue.get("state") or {}).get("name") or "?",
                "suggested_status": suggested,
                "reason": reason,
            })
        return proposals

    @staticmethod
    def _suggest_status(
        binding,
        updated: datetime,
        stale_days: int,
    ) -> tuple[str, str]:
        days_stale = (datetime.now(timezone.utc) - updated).days
        if binding:
            gmail = binding.platforms.get("gmail") or {}
            if gmail.get("archived"):
                return "Done", "Gmail archived; issue still open in Linear"
        if days_stale >= stale_days * 2:
            return "Canceled", f"No activity for {days_stale} days"
        return "Review", f"No activity for {days_stale} days"

    @staticmethod
    def _render_report(proposals: list[dict[str, Any]], *, stale_days: int) -> str:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            "# Stale Audit",
            "",
            f"_Audit {now}. Stale threshold: **{stale_days}** days without update._",
            "",
        ]
        if not proposals:
            lines.append("No stale open issues detected.")
            return "\n".join(lines).rstrip() + "\n"

        lines.extend(["## Proposed updates", ""])
        for p in proposals:
            lines.append(
                f"- **{p['identifier']}** — {p['title']} "
                f"({p['current_status']} → suggested: {p['suggested_status']})"
            )
            if p.get("reason"):
                lines.append(f"  - {p['reason']}")
        lines.append("")
        lines.append("_Actionable items dispatched to Manual Management checklist._")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"
