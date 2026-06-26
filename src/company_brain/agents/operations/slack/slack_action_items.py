"""Slack Action Items Agent — create Linear tasks from thread action items.

Specialist dispatched by ``slack_thread_watcher`` when a watched thread contains
action-item language. Creates wiki binding + Linear issue (origin-aware fan-out).

SDK: Neither (Slack SDK via ``slack_client`` + Linear GraphQL).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.linear import linear_client
from company_brain.agents.engineering.linear.task_bindings import TaskBindingStore
from company_brain.agents.engineering.shared.linear_config import (
    default_priority,
    task_class_fan_out,
    team_id,
    team_key,
)
from company_brain.agents.operations.slack import slack_client
from company_brain.agents.operations.slack.action_items import extract_action_title
from company_brain.config import AppConfig


class SlackActionItemsAgent(BaseAgent):
    """Bind a Slack thread action item to Linear."""

    name = "slack_action_items"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._bindings = TaskBindingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return slack_client.slack_is_configured() and linear_client.linear_is_configured()

    def run(
        self,
        *,
        channel: str,
        thread_ts: str,
        message_ts: str | None = None,
        text: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if "linear" not in task_class_fan_out("slack_action"):
            return {"status": "skipped", "reason": "fan_out"}

        if self._bindings.find_by_slack_thread(channel, thread_ts):
            return {"status": "skipped", "reason": "already_bound"}

        body = text or self._message_text(channel, thread_ts, message_ts)
        title = extract_action_title(body)
        link = ""
        if message_ts:
            link = slack_client.permalink(channel, message_ts)

        description = (
            f"From Slack thread in `{channel}`.\n\n"
            f"**Thread:** `{thread_ts}`\n\n"
            f"{body}\n"
        )
        if link:
            description += f"\n**Permalink:** {link}"

        issue = linear_client.create_issue(
            title=f"[Slack] {title}",
            description=description,
            team_id=team_id() or None,
            team_key=team_key() or None,
            priority=default_priority(),
        )
        binding = self._bindings.create_slack_binding(
            channel=channel,
            thread_ts=thread_ts,
            message_ts=message_ts or thread_ts,
            linear_issue=issue,
            title=title,
            task_class="slack_action",
            sync_notion=False,
        )
        return {
            "status": "created",
            "task_id": binding.task_id,
            "linear": issue.get("identifier"),
        }

    @staticmethod
    def _message_text(channel: str, thread_ts: str, message_ts: str | None) -> str:
        messages = slack_client.fetch_thread_replies(channel, thread_ts)
        if message_ts:
            for msg in messages:
                if msg.get("ts") == message_ts:
                    return str(msg.get("text") or "")
        if messages:
            return str(messages[-1].get("text") or "")
        return ""
