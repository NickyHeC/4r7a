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
            from company_brain.agents.engineering.linear.linear_completed.slack_thread_respond import (
                SlackThreadRespondAgent,
            )

            results["platforms"]["slack"] = SlackThreadRespondAgent(self.config).run(
                binding=binding,
                linear_status=linear_status,
            )

        if "notion" in fan_out:
            from company_brain.agents.operations.notion.notion_task_sync import NotionTaskSyncAgent

            results["platforms"]["notion"] = NotionTaskSyncAgent(self.config).run(
                binding=binding,
                linear_status=linear_status,
                create_if_missing=True,
            )

        return results
