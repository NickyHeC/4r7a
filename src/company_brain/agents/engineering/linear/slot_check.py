"""Slot Check Agent — validate Linear issues sit in the correct team/project.

Propose-only: writes a wiki report; does not auto-move issues unless config enables it.
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.linear import linear_client
from company_brain.agents.engineering.shared.linear_config import slot_check_cfg, team_id, team_key
from company_brain.wiki.publish import write_wiki_page

REPORT_PATH = "engineering/linear/slot-check.md"
REPORT_TITLE = "Slot Check"


class SlotCheckAgent(BaseAgent):
    """Report misfiled Linear issues (team/project/milestone)."""

    name = "linear_slot_check"
    WRITE_MODE = "update"

    def should_run(self, **kwargs: Any) -> bool:
        return linear_client.linear_is_configured()

    def run(self, *, first: int = 100, sync: bool = True, **kwargs: Any) -> dict[str, Any]:
        issues = linear_client.list_issues(
            team_id=team_id() or None,
            team_key=team_key() or None,
            first=first,
        )
        expected_key = (team_key() or "").lower()
        findings: list[str] = []

        for issue in issues:
            ident = issue.get("identifier") or issue.get("id") or "?"
            team = issue.get("team") or {}
            project = issue.get("project")
            problems: list[str] = []
            if expected_key and team.get("key", "").lower() != expected_key:
                problems.append(
                    f"team `{team.get('key')}` != expected `{team_key()}`"
                )
            if project is None:
                problems.append("missing project")
            if problems:
                url = issue.get("url") or ""
                line = f"- **{ident}** — {', '.join(problems)}"
                if url:
                    line += f" ([open]({url}))"
                findings.append(line)

        body = self._render_body(findings, auto_move=bool(slot_check_cfg().get("auto_move")))
        write_wiki_page(
            REPORT_PATH,
            REPORT_TITLE,
            body,
            mode="update",
            section="engineering/linear",
            sync=sync,
        )
        return {"checked": len(issues), "findings": len(findings)}

    @staticmethod
    def _render_body(findings: list[str], *, auto_move: bool) -> str:
        lines = [
            "# Slot Check",
            "",
            f"_Auto-move: {'enabled' if auto_move else 'disabled (propose-only)'}_",
            "",
        ]
        if not findings:
            lines.append("All checked issues match team/project expectations.")
        else:
            lines.append("## Misfiled or incomplete")
            lines.append("")
            lines.extend(findings)
        return "\n".join(lines).rstrip() + "\n"
