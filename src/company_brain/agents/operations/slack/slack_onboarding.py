"""Slack Onboarding — $0 estimate and operational backfill.

Runs once on first Slack connection: counts messages in scope, backfills routing
records via ``ingest_triage``, optional absorb on raw entries, then starts
``slack_manager``.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.slack import channels_config, slack_client
from company_brain.agents.operations.slack import slack_config as cfg
from company_brain.agents.operations.slack.ingest_triage import IngestTriageAgent

AGENT_KEY = "slack_onboarding"


class SlackOnboardingAgent(BaseAgent):
    """One-time Slack setup: estimate, backfill ingest, hand off to manager."""

    name = "slack_onboarding"

    def run(
        self,
        *,
        start_manager: bool = True,
        backfill_days: int | None = None,
        all_history: bool = False,
        absorb: bool = False,
        estimate_only: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not slack_client.slack_is_configured():
            return {"status": "not_configured"}

        days = (
            backfill_days if backfill_days is not None else cfg.onboarding_default_backfill_days()
        )
        estimate = estimate_backfill(
            days=days if not all_history else None,
            all_history=all_history,
        )
        if estimate_only:
            return {"status": "estimate", **estimate}

        if all_history:
            backfill_result = self._backfill_all()
        else:
            backfill_result = self._backfill_days(days)

        absorb_result: dict[str, Any] | None = None
        if absorb or cfg.onboarding_absorb_default():
            absorb_result = self._run_absorb()

        if start_manager:
            self._start_manager()

        return {
            "status": "ok",
            "estimate": estimate,
            "backfill": backfill_result,
            "absorb": absorb_result,
        }

    def _backfill_days(self, days: int) -> dict[str, Any]:
        oldest = datetime.now(timezone.utc) - timedelta(days=days)
        return self._backfill_since(oldest.timestamp())

    def _backfill_all(self) -> dict[str, Any]:
        return self._backfill_since(None)

    def _backfill_since(self, oldest: float | None) -> dict[str, Any]:
        triage = IngestTriageAgent(self.config)
        messages = 0
        routed = 0
        registry = channels_config.load_channels_registry().get("channels") or {}
        for channel_id, entry in registry.items():
            if not isinstance(entry, dict):
                continue
            if str(entry.get("ingest_mode") or "hot") == "out_of_scope":
                continue
            try:
                batch = slack_client.fetch_channel_messages_by_id(
                    channel_id,
                    oldest=oldest,
                    limit=200,
                )
            except slack_client.SlackClientError:
                continue
            for msg in batch:
                messages += 1
                result = triage.process_message(channel_id, msg)
                if result.get("status") == "routed":
                    routed += 1
        return {"messages": messages, "routed": routed}

    def _run_absorb(self) -> dict[str, Any]:
        try:
            from company_brain.wiki.absorb import AbsorbWriter

            writer = AbsorbWriter()
            result = writer.run()
            return dict(result)
        except Exception as exc:
            self.logger.warning("Optional absorb skipped: %s", exc)
            return {"status": "skipped", "reason": str(exc)}

    def _start_manager(self) -> None:
        from company_brain.agents.operations.slack_manager import SlackManager
        from company_brain.runtime import get_runtime

        get_runtime().start(SlackManager, self.config)


def estimate_backfill(*, days: int | None = 30, all_history: bool = False) -> dict[str, Any]:
    """$0 message/thread count estimate for onboarding."""
    if not slack_client.slack_is_configured():
        return {"status": "not_configured"}

    message_count = 0
    thread_roots = 0
    channels_scanned = 0
    oldest = None
    if not all_history and days is not None:
        oldest = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()

    registry = channels_config.load_channels_registry().get("channels") or {}
    if not registry:
        channels = slack_client.list_channels()
        channels_config.sync_from_slack_api(channels)
        registry = channels_config.load_channels_registry().get("channels") or {}

    for channel_id, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("ingest_mode") or "hot") == "out_of_scope":
            continue
        channels_scanned += 1
        try:
            batch = slack_client.fetch_channel_messages_by_id(
                channel_id,
                oldest=oldest,
                limit=200,
            )
        except slack_client.SlackClientError:
            continue
        message_count += len(batch)
        thread_roots += sum(1 for m in batch if m.get("thread_ts") == m.get("ts"))

    debounce = cfg.debounce_minutes()
    projected_batches = max(1, message_count // max(debounce, 1))
    token_estimate = projected_batches * 150

    return {
        "channels_scanned": channels_scanned,
        "message_count": message_count,
        "thread_roots": thread_roots,
        "projected_tier1_batches": projected_batches,
        "token_estimate": token_estimate,
        "window_days": None if all_history else days,
    }
