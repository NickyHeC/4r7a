"""Employee Offboarding — proposal-only HR runbook (admin confirms actuation).

Writes ``hr/offboard-proposal/{member}.md`` and asks admin. Actuation is
``offboard_confirm`` via ``company-brain hr confirm-offboard``.

SDK: Neither (wiki + notify).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.hr.hiring_log import append_hiring_log
from company_brain.agents.hr.shared.hr_slack import hr_notifier
from company_brain.members_config import load_members_config
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import UPDATE, write_wiki_page

PROPOSAL_DIR = "hr/offboard-proposal"


class EmployeeOffboardingAgent(BaseAgent):
    """Compile an offboarding proposal for admin review."""

    name = "employee_offboarding"
    WRITE_MODE = UPDATE

    def run(
        self,
        *,
        member_key: str,
        reason: str = "departure",
        slack_user_id: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        members = load_members_config()
        spec = members.get(member_key)
        if spec is None:
            return {"status": "skipped", "reason": "unknown_member"}

        rel_path = f"{PROPOSAL_DIR}/{member_key}.md"
        body = _proposal_body(member_key, spec, reason=reason, slack_user_id=slack_user_id)
        write_wiki_page(
            rel_path,
            f"Offboard Proposal — {member_key}",
            body,
            mode=self.WRITE_MODE,
            section="hr",
            type_="proposal",
            extra_frontmatter={
                "member": member_key,
                "status": "proposed",
                "reason": reason,
            },
        )

        append_hiring_log(
            f"Offboard proposed — {member_key}",
            f"Proposal at `{rel_path}`.\n\nReason: {reason}",
            trigger="employee_offboarding",
            why=member_key,
        )

        hr_notifier().emit(
            Signal(
                text=(
                    f"*Offboard proposal* — `{member_key}`\n"
                    f"Review `{rel_path}`. Confirm: "
                    f"`company-brain hr confirm-offboard {member_key}`"
                ),
                severity=ACTIONABLE,
            )
        )
        return {
            "status": "proposed",
            "member": member_key,
            "wiki_path": rel_path,
            "signals": self._signal_stubs(spec),
        }

    def _signal_stubs(self, spec) -> dict[str, str]:
        return {
            "slack": "detected" if spec.bindings.slack_user_id else "not_applicable",
            "google_workspace": "stub_pending",
            "notion": "stub_pending",
            "bridge_token_revoke": "on_confirm",
        }


def _proposal_body(member_key: str, spec, *, reason: str, slack_user_id: str) -> str:
    now = datetime.now(timezone.utc).isoformat()
    slack_id = slack_user_id or spec.bindings.slack_user_id
    lines = [
        f"# Offboard Proposal — {member_key}",
        "",
        f"**Proposed at:** {now}",
        f"**Reason:** {reason}",
        f"**Email:** {spec.email}",
        f"**Department:** {spec.department or '—'}",
        f"**Role:** {getattr(spec, 'role', None) or '—'}",
        "",
        "## Checklist (admin confirms)",
        "",
        "### 4r7a actuation (safe)",
        "",
        f"- [ ] Run `company-brain hr confirm-offboard {member_key}`",
        "  - Sets `status: departed`, stops ingest, sets `departed_at`",
        "  - Revokes bridge token immediately (hash removed from bridge-tokens)",
        "  - Schedules employee wiki archive (GitHub branch + unmount after delay)",
        "- [ ] Confirm `employee_wiki/{member}/` will archive; no content deletion before archive",
        "- [ ] Review `query_grants` that reference this member; remove grants after confirm",
        "",
        "### Platform (manual — 4r7a never deletes accounts)",
        "",
        "- [ ] Revoke Slack access (workspace admin)",
        "- [ ] Google Workspace — remove / suspend **manually** "
        "(4r7a detect-only; no API deletion)",
        "- [ ] Notion — remove / deactivate **manually** (4r7a detect-only; no API deletion)",
        "- [ ] GitHub org membership / SSO — remove **manually** if applicable",
        "- [ ] Shared drives / calendar resources — transfer ownership **manually**",
        "- [ ] Linear / other SaaS — revoke **manually** as needed",
        "",
        "### Out of scope for 4r7a",
        "",
        "- Workspace / Notion account deletion APIs (explicitly not built)",
        "- Auto-wiping company wiki pages authored by the member",
        "",
        "## Bindings snapshot",
        "",
        f"- Slack: `{slack_id or '—'}`",
        f"- Gmail: `{spec.bindings.gmail_mailbox or '—'}`",
        f"- Linear: `{spec.bindings.linear_user_id or '—'}`",
        f"- LinkedIn: `{spec.bindings.linkedin_url or '—'}`",
        f"- Bridge departments: `{', '.join(spec.bridge.departments) or '—'}`",
        "",
    ]
    return "\n".join(lines)
