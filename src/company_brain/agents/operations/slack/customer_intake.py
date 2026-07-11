"""Slack Customer Intake — Connect and customer channels → customer_support.

Scans Slack routing records flagged ``customer=True`` and dispatches the
cross-platform ``customer_support`` orchestrator.

SDK: Neither (Slack read + orchestration).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.customer_support import (
    CustomerIntake,
    CustomerSupportOrchestrator,
)
from company_brain.agents.operations.slack import channels_config, slack_client
from company_brain.agents.operations.slack.routing import SlackRoutingRecord, SlackRoutingStore
from company_brain.config import AppConfig

SPECIALIST_KEY = "customer_intake"


class CustomerIntakeAgent(BaseAgent):
    """Process customer Slack threads through the customer_support orchestrator."""

    name = "customer_intake"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._routing = SlackRoutingStore()
        self._orchestrator = CustomerSupportOrchestrator()

    def should_run(self, **kwargs: Any) -> bool:
        return slack_client.slack_is_configured()

    def run(
        self,
        *,
        channel: str | None = None,
        thread_ts: str | None = None,
        record: SlackRoutingRecord | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if record is not None:
            return self._handle_record(record)

        if channel and thread_ts:
            existing = self._routing.read(channel, thread_ts)
            if existing:
                return self._handle_record(existing)
            return {"status": "skipped", "reason": "no_record"}

        processed = 0
        for rec in self._iter_pending():
            try:
                out = self._handle_record(rec)
                if out.get("status") == "processed":
                    processed += 1
            except Exception:
                self.logger.exception(
                    "Customer intake failed for %s:%s", rec.channel, rec.thread_ts
                )
        return {"processed": processed}

    def _iter_pending(self):
        for rec in self._routing.iter_open():
            if not rec.customer:
                continue
            if rec.handled.get(SPECIALIST_KEY):
                continue
            channel_id = str((rec.extracted or {}).get("channel_id") or "")
            if channel_id and not _customer_channel_allowed(channel_id):
                continue
            yield rec

    def _handle_record(self, record: SlackRoutingRecord) -> dict[str, Any]:
        if record.handled.get(SPECIALIST_KEY):
            return {"status": "skipped", "reason": "already_handled"}

        channel_id = str((record.extracted or {}).get("channel_id") or "")
        if channel_id and not _customer_channel_allowed(channel_id):
            return {"status": "skipped", "reason": "channel_not_enabled"}

        text, user_id = self._thread_text(record)
        title = (record.extracted or {}).get("title_preview") or _title_from_text(text)
        permalink = str((record.extracted or {}).get("permalink") or "")
        if not permalink:
            message_ts = str((record.extracted or {}).get("message_ts") or record.thread_ts)
            permalink = slack_client.permalink(record.channel, message_ts)

        intake = CustomerIntake(
            source="slack",
            title=title,
            body=text,
            requester_name=user_id,
            permalink=permalink,
            channel=record.channel,
            thread_ts=record.thread_ts,
            message_ts=str((record.extracted or {}).get("message_ts") or record.thread_ts),
        )
        result = self._orchestrator.process(intake)
        self._routing.mark_handled(record, SPECIALIST_KEY)
        return {"status": "processed", **result}

    def _thread_text(self, record: SlackRoutingRecord) -> tuple[str, str]:
        preview = str((record.extracted or {}).get("text_preview") or "")
        user_id = ""
        try:
            messages = slack_client.fetch_thread_replies(record.channel, record.thread_ts)
            if messages:
                root = messages[0]
                user_id = str(root.get("user") or "")
                parts = [str(m.get("text") or "") for m in messages[:5]]
                combined = "\n".join(p for p in parts if p.strip())
                if combined.strip():
                    return combined[:4000], user_id
        except slack_client.SlackClientError:
            pass
        return preview, user_id


def _customer_channel_allowed(channel_id: str) -> bool:
    entry = channels_config.get_channel(channel_id) or {}
    return bool(entry.get("customer_support"))


def _title_from_text(text: str) -> str:
    line = (text or "").strip().splitlines()[0] if text else ""
    return (line[:120] or "Customer message").strip()


def maybe_dispatch_customer_intake(
    config: AppConfig,
    *,
    channel: str,
    thread_ts: str,
    record: SlackRoutingRecord,
) -> dict[str, Any] | None:
    """Hot-lane dispatch from ingest triage when ``customer=True``."""
    if not record.customer:
        return None
    channel_id = str((record.extracted or {}).get("channel_id") or "")
    if channel_id and not _customer_channel_allowed(channel_id):
        return None
    from company_brain.runtime import get_runtime

    return get_runtime().run(
        CustomerIntakeAgent,
        config,
        channel=channel,
        thread_ts=thread_ts,
        record=record,
    )
