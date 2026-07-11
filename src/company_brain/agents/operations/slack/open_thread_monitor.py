"""Open Thread Monitor — employee open-thread wiki pages from routing records.

Scans open Slack routing records and rebuilds ``employee_wiki/{member}/open-thread.md``
for each assignee. Reaction ack/done updates flow through ``open_threads``.

SDK: Neither (wiki write + routing store).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.slack import slack_client
from company_brain.agents.operations.slack.open_threads import (
    open_threads_for_member,
    write_member_open_thread_page,
)
from company_brain.agents.operations.slack.routing import SlackRoutingRecord, SlackRoutingStore
from company_brain.config import AppConfig
from company_brain.members_config import load_members_config


class OpenThreadMonitorAgent(BaseAgent):
    """Rebuild per-member open thread pages from routing records."""

    name = "open_thread_monitor"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._routing = SlackRoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return slack_client.slack_is_configured()

    def run(self, **kwargs: Any) -> dict[str, Any]:
        open_records = list(self._routing.iter_open())
        self.enrich_permalinks(open_records)
        return self.refresh_all_member_pages(self._routing)

    @classmethod
    def refresh_all_member_pages(cls, store: SlackRoutingStore | None = None) -> dict[str, Any]:
        routing = store or SlackRoutingStore()
        open_records = list(routing.iter_open())
        updated = 0
        for member_key in load_members_config().active_members():
            member_records = open_threads_for_member(member_key, open_records)
            write_member_open_thread_page(member_key, member_records)
            updated += 1
        return {"status": "ok", "members": updated, "open_records": len(open_records)}

    @staticmethod
    def enrich_permalinks(records: list[SlackRoutingRecord]) -> None:
        for record in records:
            extracted = dict(record.extracted or {})
            if extracted.get("permalink"):
                continue
            message_ts = str(extracted.get("message_ts") or record.thread_ts)
            link = slack_client.permalink(record.channel, message_ts)
            if link:
                extracted["permalink"] = link
                record.extracted = extracted
