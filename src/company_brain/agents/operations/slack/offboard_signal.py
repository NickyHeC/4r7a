"""Slack Offboard Signal — detect deactivation and propose HR offboarding.

v1: handles ``user_change`` deletions when present and explicit CLI triggers.
Does not auto-actuate removals.

SDK: Neither (event hook + HR dispatch).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.config import AppConfig
from company_brain.members_config import load_members_config


class OffboardSignalAgent(BaseAgent):
    """Translate Slack offboarding signals into HR proposals."""

    name = "offboard_signal"

    def run(
        self,
        *,
        slack_user_id: str | None = None,
        event: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        user_id = slack_user_id or _deleted_user_from_event(event or {})
        if not user_id:
            return {"status": "skipped", "reason": "no_user"}

        members = load_members_config()
        member_key = members.find_by_slack_user_id(user_id)
        if not member_key:
            return {"status": "skipped", "reason": "not_a_member"}

        from company_brain.agents.hr.employee_offboarding import EmployeeOffboardingAgent
        from company_brain.runtime import get_runtime

        return get_runtime().run(
            EmployeeOffboardingAgent,
            self.config,
            member_key=member_key,
            reason="slack_signal",
            slack_user_id=user_id,
        )


def handle_user_change_event(event: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    if not _is_deactivation(event):
        return {"status": "ignored"}
    from company_brain.agents.operations.slack.offboard_signal import OffboardSignalAgent
    from company_brain.runtime import get_runtime

    return get_runtime().run(OffboardSignalAgent, config, event=event)


def _deleted_user_from_event(event: dict[str, Any]) -> str:
    user = event.get("user") or {}
    if isinstance(user, dict) and user.get("deleted"):
        return str(user.get("id") or "")
    if event.get("deleted"):
        return str(event.get("user") or "")
    return ""


def _is_deactivation(event: dict[str, Any]) -> bool:
    if str(event.get("type") or "") != "user_change":
        return False
    user = event.get("user") or {}
    return bool(isinstance(user, dict) and user.get("deleted"))
