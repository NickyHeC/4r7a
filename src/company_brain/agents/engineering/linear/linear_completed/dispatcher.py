"""Linear Completed Agent — dispatch completion propagation to platform specialists.

Triggered by ``linear_manager`` when a bound issue reaches Done/Canceled.
Routes to Gmail archive (and later Slack respond) based on ``task_bindings``.
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.linear.task_bindings import TaskBindingStore
from company_brain.agents.engineering.shared.linear_config import task_class_fan_out
from company_brain.config import AppConfig


class LinearCompletedAgent(BaseAgent):
    """Propagate a terminal Linear state to bound peripheral platforms."""

    name = "linear_completed"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._bindings = TaskBindingStore()

    def run(
        self,
        *,
        task_id: str | None = None,
        linear_issue: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        binding = None
        if task_id:
            binding = self._bindings.get(task_id)
        if binding is None and linear_issue:
            ref = linear_issue.get("id") or linear_issue.get("identifier") or ""
            binding = self._bindings.find_by_linear(ref)
        if binding is None:
            return {"status": "skipped", "reason": "no_binding"}

        linear_status = (linear_issue or {}).get("state", {}).get("name") or "Done"
        fan_out = task_class_fan_out(binding.task_class)
        results: dict[str, Any] = {"task_id": binding.task_id, "platforms": {}}

        if "gmail" in fan_out and binding.platforms.get("gmail"):
            from company_brain.agents.engineering.linear.linear_completed.archive_gmail import (
                ArchiveGmailAgent,
            )

            results["platforms"]["gmail"] = ArchiveGmailAgent(self.config).run(
                binding=binding,
                linear_status=linear_status,
            )

        if "slack" in fan_out and binding.platforms.get("slack"):
            from .slack_thread_respond import SlackThreadRespondAgent

            results["platforms"]["slack"] = SlackThreadRespondAgent(self.config).run(
                binding=binding,
                linear_status=linear_status,
            )

        if "notion" in fan_out:
            from company_brain.agents.operations.notion.task_sync import TaskSyncAgent

            results["platforms"]["notion"] = TaskSyncAgent(self.config).run(
                binding=binding,
                linear_status=linear_status,
                create_if_missing=True,
            )

        results["employee_wiki"] = self._record_employee_work_event(
            binding, linear_issue or {}, linear_status,
        )

        return results

    def _record_employee_work_event(
        self,
        binding: Any,
        linear_issue: dict[str, Any],
        linear_status: str,
    ) -> dict[str, Any]:
        from company_brain.agents.employee_wiki.work_event_materializer import (
            record_linear_work_event,
        )
        from company_brain.members_config import resolve_member_for_binding

        member = resolve_member_for_binding(binding)
        if not member:
            return {"status": "skipped", "reason": "no_member"}

        issue = linear_issue or {}
        linear = binding.linear or {}
        event = record_linear_work_event(
            primary_member=member,
            issue_id=str(issue.get("id") or linear.get("issue_id") or ""),
            identifier=str(issue.get("identifier") or linear.get("identifier") or ""),
            title=str(binding.title or issue.get("title") or ""),
            status=linear_status,
            url=str(issue.get("url") or linear.get("url") or ""),
            event_type="linear_completed",
            company_links=[f"engineering/tasks/{binding.department}/{binding.project}/{binding.task_id}.md"],
        )
        return {"status": "recorded", "event_id": event.event_id, "member": member}
