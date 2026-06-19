"""Inbox Triage Agent — the only raw-mail reader.

Persistent agent: every 30 minutes on workdays, pulls new mail via Gmail
historyId (or backfill query), classifies once with Phase-1 heuristics,
applies labels + disposition, and writes routing records. Does not dispatch
specialists (gmail_manager does that at 8/12/4).

SDK: Neither for classification (deterministic heuristics). Uses Gmail REST
for fetch/modify and shared routing store on the wiki volume.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.classify import classify_message
from company_brain.agents.operations.shared.gmail_config import (
    backfill_days,
    mailbox_id,
    triage_interval_minutes,
    workdays_only,
)
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.agents.operations.shared.scheduling import is_workday, next_interval
from company_brain.agents.operations.shared.triage_apply import apply_triage, collect_message_ids
from company_brain.config import AppConfig


class InboxTriageAgent(BaseAgent):
    """Persistent triage loop — classify new inbound mail every 30 minutes."""

    name = "gmail_inbox_triage"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def run(self, *, once: bool = False, backfill: bool = False, **kwargs: Any) -> Any:
        if once:
            return self.run_once(backfill=backfill)
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        self.logger.info("Inbox triage starting persistent loop (every %dm)", triage_interval_minutes())
        while True:
            now = datetime.now()
            if not workdays_only() or is_workday(now):
                try:
                    self.run_once()
                except Exception:
                    self.logger.exception("Triage run failed")
            nxt = next_interval(
                datetime.now(),
                triage_interval_minutes(),
                workdays_only=workdays_only(),
            )
            wait = (nxt - datetime.now()).total_seconds()
            self.logger.info("Next triage at %s (sleep %.0fs)", nxt.isoformat(), wait)
            await asyncio.sleep(max(wait, 1))

    def run_once(self, *, backfill: bool = False) -> dict[str, Any]:
        query = None
        if backfill:
            query = f"in:inbox newer_than:{backfill_days()}d"
        ids = collect_message_ids(mailbox=self.mailbox, backfill_query=query)
        self.logger.info("Triage processing %d message(s)", len(ids))

        results = []
        for msg_id in ids:
            if self._store.exists(self.mailbox, msg_id):
                continue
            try:
                message = rest.get_message(msg_id, mailbox=self.mailbox)
                triage = classify_message(message, mailbox=self.mailbox)
                results.append(apply_triage(msg_id, triage, mailbox=self.mailbox, store=self._store))
            except Exception:
                self.logger.exception("Failed to triage message %s", msg_id)

        profile = rest.get_profile(self.mailbox)
        from company_brain.agents.operations.shared.gmail_state import GmailState
        GmailState().set_history_id(self.mailbox, str(profile.get("historyId", "")))

        return {"processed": len(results), "results": results}
