"""Archive Gmail messages when a bound Linear issue reaches a terminal state."""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.linear.task_bindings import TaskBinding, TaskBindingStore
from company_brain.agents.engineering.linear.task_propagate import record_status_change
from company_brain.agents.operations.shared.labels import archive
from company_brain.config import AppConfig

SYSTEM_SOURCE = "system:linear_completed"


class ArchiveGmailAgent(BaseAgent):
    """Archive a bound Gmail message and record a system-originated status change."""

    name = "linear_completed_archive_gmail"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._bindings = TaskBindingStore()

    def run(self, *, binding: TaskBinding, linear_status: str, **kwargs: Any) -> dict[str, Any]:
        gmail = binding.platforms.get("gmail") or {}
        message_id = gmail.get("message_id")
        mailbox = gmail.get("mailbox") or "me"
        if not message_id:
            return {"status": "skipped", "reason": "no_gmail_binding"}

        if gmail.get("archived"):
            return {"status": "skipped", "reason": "already_archived"}

        archive(message_id, mailbox=mailbox)
        binding.platforms.setdefault("gmail", {})
        binding.platforms["gmail"]["archived"] = True

        record_status_change(
            binding,
            platform="gmail",
            field="archived",
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

        return {"status": "archived", "message_id": message_id, "mailbox": mailbox}
