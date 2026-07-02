"""Thread Watcher — sent-folder delta for Decision + Ingest enrichment.

Persistent agent: every 15 minutes on workdays, watches Gmail history for new
sent mail. Classifies each sent message (decision vs ack vs ingest-worthy),
updates routing records, applies the Decision label, and dispatches
decision_propagate / ingest as needed.

SDK: Neither for classification (deterministic heuristics).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.decision import classify_sent_message
from company_brain.agents.operations.shared.gmail_config import (
    mailbox_id,
    thread_watcher_interval_minutes,
    workdays_only,
)
from company_brain.agents.operations.shared.gmail_state import GmailState
from company_brain.agents.operations.shared.labels import apply_labels
from company_brain.agents.operations.shared.profiles import agent_enabled, profile_spec
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.agents.operations.shared.scheduling import is_workday, next_interval
from company_brain.config import AppConfig

DECISION_LABEL = "Decision"
INGEST_LABEL = "Ingest"


class ThreadWatcherAgent(BaseAgent):
    """Watch sent-folder changes and enrich routing records."""

    name = "thread_watcher"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._state = GmailState()
        self._store = RoutingStore()

    def run(self, *, once: bool = False, **kwargs: Any) -> Any:
        if once:
            return self.run_once()
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        self.logger.info(
            "Thread watcher starting persistent loop (every %dm)",
            thread_watcher_interval_minutes(),
        )
        while True:
            now = datetime.now()
            if not workdays_only() or is_workday(now):
                try:
                    self.run_once()
                except Exception:
                    self.logger.exception("Thread watcher run failed")
            nxt = next_interval(
                datetime.now(),
                thread_watcher_interval_minutes(),
                workdays_only=workdays_only(),
            )
            wait = (nxt - datetime.now()).total_seconds()
            await asyncio.sleep(max(wait, 1))

    def run_once(self) -> dict[str, Any]:
        sent_ids = self._collect_sent_ids()
        results = []
        for msg_id in sent_ids:
            try:
                results.append(self._process_sent(msg_id))
            except Exception:
                self.logger.exception("Failed to process sent message %s", msg_id)

        profile = rest.get_profile(self.mailbox)
        self._state.set_sent_history_id(self.mailbox, str(profile.get("historyId", "")))
        return {"processed": len(results), "results": results}

    def _collect_sent_ids(self) -> list[str]:
        history_id = self._state.get_sent_history_id(self.mailbox)
        if history_id:
            try:
                ids, latest = rest.history_sent_message_ids(history_id, mailbox=self.mailbox)
                if latest:
                    self._state.set_sent_history_id(self.mailbox, latest)
                return ids
            except rest.GmailAPIError as e:
                if e.status == 404:
                    self._state.set_sent_history_id(self.mailbox, "")
                else:
                    raise
        profile = rest.get_profile(self.mailbox)
        self._state.set_sent_history_id(self.mailbox, str(profile.get("historyId", "")))
        return []

    def _process_sent(self, message_id: str) -> dict[str, Any]:
        message = rest.get_message(message_id, mailbox=self.mailbox)
        thread_id = message.get("threadId", "")
        kind = classify_sent_message(message)

        if kind == "ack":
            return {"message_id": message_id, "kind": "ack", "action": "skipped"}

        add_tags: list[str] = []
        extracted: dict[str, Any] = {"sent_message_id": message_id}

        if kind == "decision" and profile_spec(self.mailbox).allows_domain(DECISION_LABEL):
            add_tags.append(DECISION_LABEL)
            extracted["decision"] = True
        elif kind == "ingest" and profile_spec(self.mailbox).allows_domain(INGEST_LABEL):
            add_tags.append(INGEST_LABEL)
            extracted["ingest_status"] = "pending"

        if add_tags:
            for tag in add_tags:
                rest.ensure_label(tag, visible=False, mailbox=self.mailbox)
            apply_labels(message_id, add=add_tags, mailbox=self.mailbox)

        updated = self._store.upsert_thread_tags(
            self.mailbox,
            thread_id,
            add_tags=add_tags,
            extracted=extracted,
        )

        if kind == "decision" and agent_enabled("decision_propagate", self.mailbox):
            self._dispatch_decision_propagate(thread_id, message_id)
        if kind == "ingest" and agent_enabled("ingest", self.mailbox):
            self._dispatch_ingest(thread_id)

        return {
            "message_id": message_id,
            "thread_id": thread_id,
            "kind": kind,
            "updated_records": len(updated),
        }

    def _dispatch_decision_propagate(self, thread_id: str, message_id: str) -> None:
        from company_brain.agents.operations.gmail.decision_propagate import DecisionPropagateAgent
        from company_brain.runtime import get_runtime

        try:
            get_runtime().run(
                DecisionPropagateAgent,
                self.config,
                mailbox=self.mailbox,
                thread_id=thread_id,
                message_id=message_id,
            )
        except Exception:
            self.logger.exception("decision_propagate dispatch failed")

    def _dispatch_ingest(self, thread_id: str) -> None:
        from company_brain.agents.operations.gmail.ingest import IngestAgent
        from company_brain.runtime import get_runtime

        try:
            get_runtime().run(
                IngestAgent,
                self.config,
                mailbox=self.mailbox,
                thread_id=thread_id,
            )
        except Exception:
            self.logger.exception("ingest dispatch failed")
