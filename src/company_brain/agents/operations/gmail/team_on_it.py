"""Team On It Agent — delegate ``4. Team On It`` mail via Linear + Slack.

Creates a Linear issue for the team lead and posts a summary to the configured
Slack channel. Gmail literal forward is not used (send scope forbidden); the
team picks up work from Slack + Linear. Archive happens via Slack/Linear
completion, not inbox_sweep.

SDK: Neither (Linear GraphQL + Slack SDK).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.linear import linear_client
from company_brain.agents.engineering.linear.task_bindings import TaskBindingStore
from company_brain.agents.engineering.shared.linear_config import (
    default_priority,
    team_id,
    team_key,
)
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import mailbox_id, team_on_it_slack_channel
from company_brain.agents.operations.shared.mail_body import plain_text
from company_brain.agents.operations.shared.operations_slack import channel_notifier
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig
from company_brain.notify import ACTIONABLE, Signal

SPECIALIST_KEY = "team_on_it"


class TeamOnItAgent(BaseAgent):
    """Linear task + Slack handoff for Team On It attention mail."""

    name = "team_on_it"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()
        self._bindings = TaskBindingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return linear_client.linear_is_configured() and bool(
            self._store.unhandled_for(
                SPECIALIST_KEY, mailbox=self.mailbox, attention="4. Team On It",
            )
        )

    def run(self, **kwargs: Any) -> dict[str, Any]:
        handled = 0
        channel = team_on_it_slack_channel()
        notifier = channel_notifier(channel)

        for record in self._store.unhandled_for(
            SPECIALIST_KEY, mailbox=self.mailbox, attention="4. Team On It",
        ):
            try:
                message = rest.get_message(record.message_id, mailbox=self.mailbox)
                subject = record.extracted.get("subject") or rest.message_subject_from(message)
                from_ = record.extracted.get("from") or rest.message_from(message)
                body = plain_text(message, max_chars=3000)
                description = (
                    f"Delegated from Gmail ({self.mailbox}).\n\n"
                    f"**From:** {from_}\n\n"
                    f"**Message:** `{record.message_id}`\n\n"
                    f"{body}"
                )
                issue = linear_client.create_issue(
                    title=f"[Team] {subject or 'Gmail delegation'}",
                    description=description,
                    team_id=team_id() or None,
                    team_key=team_key() or None,
                    priority=default_priority(),
                )
                ident = issue.get("identifier") or issue.get("id", "")
                url = issue.get("url", "")
                binding = self._bindings.create_gmail_binding(
                    message_id=record.message_id,
                    thread_id=record.thread_id,
                    mailbox=self.mailbox,
                    linear_issue=issue,
                    title=f"[Team] {subject or 'Gmail delegation'}",
                    task_class="team_on_it",
                    sync_notion=False,
                )
                record.extracted["linear_issue_id"] = ident
                record.extracted["linear_issue_url"] = url
                record.extracted["task_id"] = binding.task_id
                self._store.write(record)

                text = (
                    f"*Team on it* — {subject}\n"
                    f"*From:* {from_}\n"
                    f"*Linear:* {ident}"
                )
                if url:
                    text += f"\n<{url}|Open in Linear>"
                notifier.emit(Signal(text=text, severity=ACTIONABLE))

                self._store.mark_handled(record, SPECIALIST_KEY)
                self._record_employee_work_event(binding, issue, subject or "")
                handled += 1
            except Exception:
                self.logger.exception("team_on_it failed for %s", record.message_id)
        return {"handled": handled, "slack_channel": channel}

    def _record_employee_work_event(self, binding, issue: dict[str, Any], subject: str) -> None:
        from company_brain.agents.employee_wiki.work_event_materializer import record_gmail_work_event
        from company_brain.members_config import load_members_config

        member = load_members_config().find_by_gmail_mailbox(self.mailbox)
        if not member:
            return
        try:
            record_gmail_work_event(
                primary_member=member,
                message_id=binding.platforms.get("gmail", {}).get("message_id") or "",
                subject=subject,
                task_class=binding.task_class,
                linear_identifier=str(issue.get("identifier") or ""),
                url=str(issue.get("url") or ""),
                company_links=[
                    f"engineering/tasks/{binding.department}/{binding.project}/{binding.task_id}.md"
                ],
            )
        except Exception:
            self.logger.exception("Employee wiki Gmail work event failed for %s", binding.task_id)
