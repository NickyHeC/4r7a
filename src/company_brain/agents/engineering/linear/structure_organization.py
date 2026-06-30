"""Structure Organization Agent — propose Linear workspace layout from wiki + platforms.

Propose-only: writes ``engineering/linear/structure-proposal.md`` (wiki first,
Notion mirror title **Structure Proposal**), then pings Slack for review.
Does not mutate Linear until a human approves (future Slack confirm path).

SDK: Neither (deterministic scan).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.linear import linear_client
from company_brain.agents.engineering.linear.task_bindings import TaskBindingStore
from company_brain.agents.engineering.shared.linear_slack import linear_notifier
from company_brain.config import AppConfig, load_wiki_config, resolve_wiki_dir
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import write_wiki_page

PROPOSAL_PATH = "engineering/linear/structure-proposal.md"
PROPOSAL_TITLE = "Structure Proposal"

DEPARTMENT_DIRS = ("engineering", "operations", "finance", "product", "growth")


class StructureOrganizationAgent(BaseAgent):
    """Scan wiki departments and Linear teams; write a structure proposal."""

    name = "linear_structure_organization"
    WRITE_MODE = "update"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._bindings = TaskBindingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return linear_client.linear_is_configured()

    def run(self, *, notify: bool = True, sync: bool = True, **kwargs: Any) -> dict[str, Any]:
        wiki_departments = self._wiki_departments()
        binding_departments = self._binding_departments()
        linear_teams = linear_client.list_teams() if linear_client.linear_is_configured() else []
        linear_keys = {str(t.get("key", "")).upper() for t in linear_teams}

        expected = sorted(set(wiki_departments) | set(binding_departments))
        missing_teams = [
            d for d in expected
            if d[:3].upper() not in linear_keys and d.upper() not in linear_keys
        ]

        body = self._render_proposal(
            expected_departments=expected,
            linear_teams=linear_teams,
            missing_teams=missing_teams,
            binding_count=len(self._bindings.list_all()),
        )
        write_wiki_page(
            PROPOSAL_PATH,
            PROPOSAL_TITLE,
            body,
            mode="update",
            section="engineering/linear",
            sync=sync,
        )

        if notify:
            self._notify_slack(len(missing_teams))

        return {
            "expected_departments": expected,
            "linear_teams": len(linear_teams),
            "missing_teams": missing_teams,
        }

    def _wiki_departments(self) -> list[str]:
        wiki_root = resolve_wiki_dir()
        found: list[str] = []
        for name in DEPARTMENT_DIRS:
            if (wiki_root / name).is_dir():
                found.append(name)
        cfg = load_wiki_config()
        for key in (cfg.sections or {}):
            if key not in found:
                found.append(key)
        return found

    @staticmethod
    def _binding_departments() -> list[str]:
        store = TaskBindingStore()
        depts = {b.department for b in store.list_all()}
        return sorted(depts)

    @staticmethod
    def _render_proposal(
        *,
        expected_departments: list[str],
        linear_teams: list[dict[str, Any]],
        missing_teams: list[str],
        binding_count: int,
    ) -> str:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            "# Structure Proposal Proposal",
            "",
            f"_Generated {now}. Review and approve before applying to Linear._",
            "",
            "## Current state",
            "",
            f"- Task bindings: **{binding_count}**",
            f"- Linear teams: **{len(linear_teams)}**",
            "",
        ]
        if linear_teams:
            lines.extend(["### Existing Linear teams", ""])
            for team in linear_teams:
                lines.append(f"- `{team.get('key', '?')}` — {team.get('name', '')}")
            lines.append("")

        lines.extend(["## Proposed department → team mapping", ""])
        for dept in expected_departments:
            key = dept[:3].upper() if len(dept) >= 3 else dept.upper()
            status = "exists" if dept not in missing_teams else " **proposed (missing)**"
            lines.append(f"- **{dept}** → Linear team `{key}`{status}")
        lines.append("")

        if missing_teams:
            lines.extend([
                "## Action required",
                "",
                "Create the following Linear teams (or map to existing teams):",
                "",
            ])
            for dept in missing_teams:
                key = dept[:3].upper() if len(dept) >= 3 else dept.upper()
                lines.append(f"- [ ] Create team `{key}` for **{dept}**")
            lines.append("")

        lines.extend([
            "## Projects (seed from wiki)",
            "",
            "For each department, create projects aligned with wiki folders:",
            "",
        ])
        for dept in expected_departments:
            lines.append(f"- `{dept}/general` — default project for {dept} tasks")
        lines.append("")
        lines.extend([
            "## Approval",
            "",
            "- [ ] Structure reviewed",
            "- [ ] Teams created or mapped",
            "- [ ] Ready to apply (manual step until Slack confirm ships)",
            "",
        ])
        return "\n".join(lines)

    def _notify_slack(self, missing_count: int) -> None:
        text = (
            "Linear structure proposal ready for review "
            f"({missing_count} team gap(s) detected). "
            "Edit the wiki page / Notion mirror **Structure Proposal**."
        )
        try:
            linear_notifier().emit(Signal(text=text, severity=ACTIONABLE))
        except Exception:
            self.logger.exception("Slack notify failed for structure proposal")
