"""Status Watch — multi-signal deactivation → admin ask (no actuation).

Slack deactivation already flows through ``offboard_signal`` → proposal.
This agent consolidates Slack + Workspace/Notion stub signals and asks admin
whether the employee has departed.

SDK: Neither (config + notify).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore, is_handled, mark_handled
from company_brain.agents.hr.shared.hr_slack import hr_notifier
from company_brain.members_config import load_members_config
from company_brain.notify import ACTIONABLE, Signal
from company_brain.roster_config import load_roster_config
from company_brain.wiki.publish import UPDATE, write_wiki_page

PROPOSAL_DIR = "hr/offboard-proposal"
ASK_PREFIX = "hr:status_ask:"


class StatusWatchAgent(BaseAgent):
    """Detect deactivation signals and ask admin if the person departed."""

    name = "status_watch"
    WRITE_MODE = UPDATE

    def __init__(self, config, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()

    def run(
        self,
        *,
        member_key: str = "",
        signals: dict[str, str] | None = None,
        reason: str = "status_watch",
        **kwargs: Any,
    ) -> dict[str, Any]:
        key = (member_key or "").strip()
        if key:
            return self._ask_for(key, signals=signals or {}, reason=reason)

        # Steady-state: stub detectors only record "unchecked" — real Slack
        # path stays on offboard_signal. This pass is for explicit CLI / future
        # Workspace/Notion hooks.
        return {
            "status": "ok",
            "checked": 0,
            "note": "pass_signals_or_member_key; slack uses offboard_signal",
            "stubs": {
                "google_workspace": "stub_pending",
                "notion": "stub_pending",
            },
        }

    def _ask_for(
        self,
        member_key: str,
        *,
        signals: dict[str, str],
        reason: str,
    ) -> dict[str, Any]:
        members = load_members_config()
        roster = load_roster_config()
        spec = members.get(member_key)
        person = roster.get(member_key)
        if spec is None and person is None:
            return {"status": "skipped", "reason": "unknown_person"}

        if spec and not spec.is_active:
            return {"status": "skipped", "reason": "already_departed"}
        if person and (person.status or "active").lower() != "active":
            return {"status": "skipped", "reason": "already_departed"}

        ask_key = f"{ASK_PREFIX}{member_key}"
        ask_sig = reason or "status_watch"
        if is_handled(ask_key, ask_sig, store=self._state):
            return {"status": "skipped", "reason": "already_asked", "member": member_key}

        email = (spec.email if spec else "") or (person.email if person else "")
        slack_bound = bool(
            (spec and spec.bindings.slack_user_id) or (person and person.slack_user_id)
        )
        merged = {
            "slack": signals.get("slack") or ("bound" if slack_bound else "not_applicable"),
            "google_workspace": signals.get("google_workspace") or "stub_pending",
            "notion": signals.get("notion") or "stub_pending",
        }

        # Members: proposal agent already emits an actionable ask.
        if spec is not None:
            from company_brain.agents.hr.employee_offboarding import EmployeeOffboardingAgent
            from company_brain.runtime import get_runtime

            proposal = get_runtime().run(
                EmployeeOffboardingAgent,
                self.config,
                member_key=member_key,
                reason=reason,
            )
            mark_handled(ask_key, ask_sig, store=self._state)
            return {
                "status": "asked",
                "member": member_key,
                "signals": merged,
                "reason": reason,
                "proposal": proposal,
            }

        rel_path = f"{PROPOSAL_DIR}/{member_key}.md"
        now = datetime.now(timezone.utc).isoformat()
        body = (
            f"# Offboard Proposal — {member_key}\n\n"
            f"**Proposed at:** {now}\n"
            f"**Reason:** {reason}\n"
            f"**Email:** {email}\n"
            f"**Employment:** roster / {(person.employment_type if person else '')}\n\n"
            "## Signals\n\n" + "\n".join(f"- **{k}:** {v}" for k, v in merged.items()) + "\n\n"
            "Admin: confirm with `company-brain hr confirm-offboard "
            f"{member_key}` if they have departed.\n"
        )
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
        hr_notifier().emit(
            Signal(
                text=(
                    f"*HR status ask* — has `{member_key}` departed?\n"
                    f"Signals: {merged}\n"
                    f"Confirm: `company-brain hr confirm-offboard {member_key}`"
                ),
                severity=ACTIONABLE,
            )
        )
        mark_handled(ask_key, ask_sig, store=self._state)
        return {
            "status": "asked",
            "member": member_key,
            "signals": merged,
            "reason": reason,
        }
