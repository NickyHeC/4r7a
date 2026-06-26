"""Inbox Task Agent — create Linear issues for Action and complex Reply mail.

``1. Action`` → always create a Linear task.
``2. Reply`` → Linear task when complexity heuristics mark the thread as complex
(draft_reply skips those).

SDK: Neither — deterministic Linear GraphQL / optional CLI.
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
from company_brain.agents.operations.shared.complexity import is_simple_reply
from company_brain.agents.operations.shared.gmail_config import mailbox_id
from company_brain.agents.operations.shared.mail_body import plain_text
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig

SPECIALIST_KEY = "inbox_task"


class InboxTaskAgent(BaseAgent):
    """Create Linear issues for action items and complex reply threads."""

    name = "gmail_inbox_task"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()
        self._bindings = TaskBindingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return linear_client.linear_is_configured() and bool(self._pending())

    def run(self, **kwargs: Any) -> dict[str, Any]:
        created = 0
        for record in self._pending():
            try:
                issue = self._create_for_record(record)
                subject = record.extracted.get("subject") or issue.get("title") or "Gmail action item"
                binding = self._bindings.create_gmail_binding(
                    message_id=record.message_id,
                    thread_id=record.thread_id,
                    mailbox=self.mailbox,
                    linear_issue=issue,
                    title=subject,
                    task_class="inbox_action",
                    sync_notion=False,
                )
                record.extracted["linear_issue_id"] = issue.get("identifier") or issue.get("id")
                record.extracted["linear_issue_url"] = issue.get("url", "")
                record.extracted["task_id"] = binding.task_id
                self._store.write(record)
                self._store.mark_handled(record, SPECIALIST_KEY)
                created += 1
            except Exception:
                self.logger.exception("Linear task failed for %s", record.message_id)
        return {"created": created}

    def _pending(self):
        out = []
        for record in self._store.unhandled_for(
            SPECIALIST_KEY, mailbox=self.mailbox, attention="1. Action",
        ):
            out.append(record)
        for record in self._store.unhandled_for(
            SPECIALIST_KEY, mailbox=self.mailbox, attention="2. Reply",
        ):
            if "draft_reply" in record.handled:
                continue
            try:
                thread = rest.get_thread(record.thread_id, mailbox=self.mailbox)
                if not is_simple_reply(thread, mailbox=self.mailbox):
                    out.append(record)
            except Exception:
                self.logger.exception("Complexity check failed for %s", record.message_id)
        return out

    def _create_for_record(self, record) -> dict[str, Any]:
        message = rest.get_message(record.message_id, mailbox=self.mailbox)
        subject = record.extracted.get("subject") or rest.message_subject_from(message)
        from_ = record.extracted.get("from") or rest.message_from(message)
        body = plain_text(message, max_chars=4000)
        description = (
            f"**From:** {from_}\n\n"
            f"**Mailbox:** {self.mailbox}\n\n"
            f"**Gmail message:** `{record.message_id}`\n\n"
            f"**Thread:** `{record.thread_id}`\n\n"
            f"{body}"
        )
        return linear_client.create_issue(
            title=subject or "Gmail action item",
            description=description,
            team_id=team_id() or None,
            team_key=team_key() or None,
            priority=default_priority(),
        )
