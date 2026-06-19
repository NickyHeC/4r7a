"""Gmail Onboarding Agent.

Runs once on first Gmail connection: ensure label taxonomy (attention visible,
domain hidden), bounded backfill triage (default 1 month), then start
gmail_manager at its next scheduled time.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

import logging
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.shared.gmail_config import backfill_days, mailbox_id
from company_brain.agents.operations.shared.labels import ensure_taxonomy
from company_brain.config import AppConfig

logger = logging.getLogger(__name__)

AGENT_KEY = "gmail_onboarding"


class GmailOnboardingAgent(BaseAgent):
    """One-time Gmail setup: labels, backfill triage, hand off to manager."""

    name = "gmail_onboarding"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()

    def run(self, *, start_manager: bool = True, backfill_days_override: int | None = None, **kwargs: Any) -> dict[str, Any]:
        self.logger.info("Starting Gmail onboarding for mailbox %s", self.mailbox)

        labels = ensure_taxonomy(self.mailbox)
        self.logger.info("Ensured %d Gmail labels", len(labels))

        from company_brain.agents.operations.shared.wiki_crm import ensure_gmail_crm_seeds
        seeded = ensure_gmail_crm_seeds()
        if seeded:
            self.logger.info("Created %d CRM seed wiki page(s)", seeded)

        from company_brain.agents.operations.gmail.inbox_triage import InboxTriageAgent

        days = backfill_days_override if backfill_days_override is not None else backfill_days()
        triage = InboxTriageAgent(self.config, mailbox=self.mailbox)
        summary = triage.run_once(backfill=True)
        self.logger.info("Backfill triage: %s", summary)

        if start_manager:
            self._start_persistent_agents()

        self.logger.info("Gmail onboarding complete")
        return {"labels": len(labels), "backfill_days": days, "triage": summary}

    def _start_persistent_agents(self) -> None:
        from company_brain.agents.operations.gmail.inbox_triage import InboxTriageAgent
        from company_brain.agents.operations.gmail.thread_watcher import ThreadWatcherAgent
        from company_brain.agents.operations.gmail_manager import GmailManager
        from company_brain.runtime import get_runtime

        self.logger.info(
            "Starting inbox_triage, thread_watcher, and gmail_manager",
        )
        try:
            get_runtime().start(InboxTriageAgent, self.config, mailbox=self.mailbox)
            get_runtime().start(ThreadWatcherAgent, self.config, mailbox=self.mailbox)
            get_runtime().start(GmailManager, self.config, mailbox=self.mailbox)
        except Exception:
            self.logger.exception("Failed to start persistent Gmail agents")
