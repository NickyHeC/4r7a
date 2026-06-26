"""Linear Onboarding Agent — one-time scan, backfill, and manager handoff.

Runs once on first Linear connection: backfills Gmail bindings, proposes workspace
structure (non-blocking), runs slot_check, starts ``linear_manager``, exits.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.linear import linear_client
from company_brain.agents.engineering.linear.task_bindings import TaskBindingStore
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig, resolve_wiki_dir

AGENT_KEY = "linear_onboarding"


class LinearOnboardingAgent(BaseAgent):
    """One-time Linear onboarding: scan, backfill bindings, start manager."""

    name = "linear_onboarding"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._bindings = TaskBindingStore()
        self._routing = RoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return linear_client.linear_is_configured()

    def run(self, *, start_manager: bool = True, **kwargs: Any) -> dict[str, Any]:
        self.logger.info("Starting Linear onboarding")

        teams = linear_client.list_teams()
        backfill = self._backfill_gmail_bindings()
        structure = self._run_structure_proposal()
        slot = self._run_slot_check()

        if start_manager:
            self._start_manager()

        self.logger.info("Linear onboarding complete")
        return {
            "teams": len(teams),
            "bindings_backfilled": backfill,
            "structure": structure,
            "slot_check": slot,
        }

    def _backfill_gmail_bindings(self) -> int:
        """Create bindings for routing records that have Linear ids but no task_id."""
        count = 0
        routing_root = resolve_wiki_dir() / "operations/gmail/routing"
        if not routing_root.exists():
            return 0

        for mailbox_dir in routing_root.iterdir():
            if not mailbox_dir.is_dir():
                continue
            mailbox = mailbox_dir.name
            for record in self._routing.iter_mailbox(mailbox):
                if record.extracted.get("task_id"):
                    continue
                linear_ref = record.extracted.get("linear_issue_id")
                if not linear_ref:
                    continue
                if self._bindings.find_by_gmail_message(record.message_id):
                    continue
                title = record.extracted.get("subject") or f"Gmail {record.message_id[:8]}"
                task_class = "team_on_it" if record.attention == "4. Team On It" else "inbox_action"
                try:
                    issue = linear_client.get_issue(linear_ref)
                except Exception:
                    issue = {
                        "id": linear_ref,
                        "identifier": linear_ref,
                        "url": record.extracted.get("linear_issue_url", ""),
                    }
                binding = self._bindings.create_gmail_binding(
                    message_id=record.message_id,
                    thread_id=record.thread_id,
                    mailbox=record.mailbox,
                    linear_issue=issue,
                    title=title,
                    task_class=task_class,
                    sync_notion=False,
                )
                record.extracted["task_id"] = binding.task_id
                self._routing.write(record)
                count += 1
        return count

    def _run_structure_proposal(self) -> dict[str, Any]:
        from company_brain.agents.engineering.linear.structure_organization import (
            StructureOrganizationAgent,
        )

        return StructureOrganizationAgent(self.config).run(notify=True, sync=True)

    def _run_slot_check(self) -> dict[str, Any]:
        from company_brain.agents.engineering.linear.slot_check import SlotCheckAgent

        return SlotCheckAgent(self.config).run(sync=True)

    def _start_manager(self) -> None:
        from company_brain.agents.engineering.linear.linear_manager import LinearManagerAgent
        from company_brain.runtime import get_runtime

        self.logger.info("Starting linear_manager (persistent poll loop)")
        try:
            get_runtime().start(LinearManagerAgent, self.config)
        except Exception:
            self.logger.exception("Failed to start linear_manager")
        self._start_notion_scanner()

    def _start_notion_scanner(self) -> None:
        from company_brain.agents.operations.notion.notion_task_config import (
            configured_database_keys,
        )
        from company_brain.agents.operations.notion.notion_task_scanner import (
            NotionTaskScannerAgent,
        )
        from company_brain.runtime import get_runtime

        if not configured_database_keys(notion=self.config.notion):
            return
        self.logger.info("Starting notion_task_scanner (persistent poll loop)")
        try:
            get_runtime().start(NotionTaskScannerAgent, self.config)
        except Exception:
            self.logger.exception("Failed to start notion_task_scanner")
