"""Employee Offboarding — proposal-only HR runbook (admin confirms actuation).

Marks member ``status: departed`` in proposal wiki page; stubs Google Workspace
and Notion removal signals for v1. Bridge token revoke remains tabled until
this agent ships steady-state.

SDK: Neither (wiki + config proposals).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.hr.hiring_log import append_hiring_log
from company_brain.members_config import load_members_config
from company_brain.wiki.publish import UPDATE, write_wiki_page

PROPOSAL_DIR = "hr/offboard-proposal"


class EmployeeOffboardingAgent(BaseAgent):
    """Compile an offboarding proposal for admin review."""

    name = "employee_offboarding"

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
            mode=UPDATE,
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

        self._notify_admin(member_key, rel_path)
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
            "bridge_token_revoke": "tabled_until_ship",
        }

    def _notify_admin(self, member_key: str, rel_path: str) -> None:
        from company_brain.agents.admin.weave_notify import weave_admin_notifier
        from company_brain.notify import ACTIONABLE, Signal

        weave_admin_notifier().emit(
            Signal(
                text=(
                    f"*Offboard proposal* — `{member_key}`\n"
                    f"Review `{rel_path}` and confirm removals manually."
                ),
                severity=ACTIONABLE,
            )
        )


def _proposal_body(member_key: str, spec, *, reason: str, slack_user_id: str) -> str:
    now = datetime.now(timezone.utc).isoformat()
    slack_id = slack_user_id or spec.bindings.slack_user_id
    lines = [
        f"# Offboard Proposal — {member_key}",
        "",
        f"**Proposed at:** {now}",
        f"**Reason:** {reason}",
        f"**Email:** {spec.email}",
        "",
        "## Checklist (admin confirms)",
        "",
        "- [ ] Mark `members.yaml` `status: departed`",
        "- [ ] Revoke Slack access",
        "- [ ] Google Workspace — _stub (v1 manual)_",
        "- [ ] Notion user removal — _stub (v1 manual)_",
        "- [ ] Bridge token revoke — _tabled until offboard ships_",
        "",
        "## Bindings snapshot",
        "",
        f"- Slack: `{slack_id or '—'}`",
        f"- Gmail: `{spec.bindings.gmail_mailbox or '—'}`",
        f"- Linear: `{spec.bindings.linear_user_id or '—'}`",
        "",
    ]
    return "\n".join(lines)
