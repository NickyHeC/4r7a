"""Post Slack thread completion note when Linear issue reaches terminal state."""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.linear.task_bindings import TaskBinding, TaskBindingStore
from company_brain.agents.engineering.linear.task_propagate import record_status_change
from company_brain.agents.operations.slack import slack_client
from company_brain.config import AppConfig

SYSTEM_SOURCE = "system:linear_completed"


class SlackThreadRespondAgent(BaseAgent):
    """Reply in the bound Slack thread when Linear completes."""

    name = "linear_completed_slack_thread_respond"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._bindings = TaskBindingStore()

    def run(self, *, binding: TaskBinding, linear_status: str, **kwargs: Any) -> dict[str, Any]:
        slack = binding.platforms.get("slack") or {}
        channel = slack.get("channel")
        thread_ts = slack.get("thread_ts")
        if not channel or not thread_ts:
            return {"status": "skipped", "reason": "no_slack_binding"}

        if slack.get("replied"):
            return {"status": "skipped", "reason": "already_replied"}

        ident = binding.linear.get("identifier") or binding.linear.get("issue_id") or "issue"
        url = binding.linear.get("url") or ""
        text = f"Linear `{ident}` marked *{linear_status}*."
        if url:
            text += f" <{url}|Open in Linear>"

        try:
            reply_ts = slack_client.post_thread_reply(channel, thread_ts, text)
        except slack_client.SlackClientError:
            self.logger.exception("Slack thread reply failed for %s", binding.task_id)
            return {"status": "error"}

        binding.platforms.setdefault("slack", {})
        binding.platforms["slack"]["replied"] = True
        binding.platforms["slack"]["reply_ts"] = reply_ts or ""

        record_status_change(
            binding,
            platform="slack",
            field="replied",
            value=True,
            source=SYSTEM_SOURCE,
            store=self._bindings,
            sync_notion=False,
        )
        record_status_change(
            binding,
            platform="linear",
            field="status",
            value=linear_status,
            source=SYSTEM_SOURCE,
            store=self._bindings,
            sync_notion=False,
        )
        self._bindings.upsert(binding, sync_notion=False)

        return {"status": "replied", "channel": channel, "thread_ts": thread_ts}
