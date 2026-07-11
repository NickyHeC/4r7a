"""Slack Thread Watcher — poll watched channels for action-item threads.

Ephemeral specialist dispatched by ``slack_manager`` on each poll pass. Runs
``ingest_triage`` on every message (poll backup) and dispatches ``action_items``
when action-item language appears.

SDK: Neither (Slack SDK + orchestration).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore, is_handled, mark_handled
from company_brain.agents.operations.slack import channels_config, slack_client
from company_brain.agents.operations.slack import slack_config as cfg
from company_brain.agents.operations.slack.action_items import message_has_action_item
from company_brain.agents.operations.slack.ingest_triage import IngestTriageAgent
from company_brain.config import AppConfig

POLL_KEY_PREFIX = "slack_thread_watch:"


class ThreadWatcherAgent(BaseAgent):
    """Poll Slack channels and dispatch action-item specialists."""

    name = "thread_watcher"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()
        self._triage = IngestTriageAgent(config, **kwargs)

    def should_run(self, **kwargs: Any) -> bool:
        return slack_client.slack_is_configured() and bool(cfg.watched_channels())

    def run(self, *, once: bool = True, **kwargs: Any) -> dict[str, Any]:
        return self.run_once()

    def run_once(self) -> dict[str, Any]:
        dispatched = 0
        scanned = 0
        triaged = 0
        for channel in cfg.watched_channels():
            count, hits, triage_hits = self._scan_channel(channel)
            scanned += count
            dispatched += hits
            triaged += triage_hits
        return {
            "channels": len(cfg.watched_channels()),
            "messages": scanned,
            "triaged": triaged,
            "dispatched": dispatched,
        }

    def _scan_channel(self, channel: str) -> tuple[int, int, int]:
        channel_id = slack_client.resolve_channel_id(channel)
        if channels_config.is_out_of_scope(channel_id):
            return 0, 0, 0

        since = self._since_timestamp(channel)
        oldest = slack_client.datetime_to_slack_ts(since)
        try:
            messages = slack_client.fetch_channel_messages(channel, oldest=oldest)
        except slack_client.SlackClientError:
            self.logger.exception("Slack fetch failed for %s", channel)
            return 0, 0, 0

        hits = 0
        triaged = 0
        seen_threads: set[str] = set()
        for msg in messages:
            triage_result = self._triage.process_message(channel_id, msg)
            if triage_result.get("status") == "routed":
                triaged += 1

            text = str(msg.get("text") or "")
            if not message_has_action_item(text):
                continue
            thread_ts = str(msg.get("thread_ts") or msg.get("ts") or "")
            message_ts = str(msg.get("ts") or "")
            if not thread_ts or thread_ts in seen_threads:
                continue
            signature = f"{channel}:{thread_ts}:{message_ts}"
            if is_handled("slack_action_item", signature, store=self._state):
                continue
            result = self._dispatch_action_items(
                channel,
                thread_ts,
                message_ts,
                text,
                str(msg.get("user") or ""),
            )
            mark_handled("slack_action_item", signature, store=self._state)
            seen_threads.add(thread_ts)
            if result.get("status") == "created":
                hits += 1

        self._state.set(f"{POLL_KEY_PREFIX}{channel}", datetime.now(timezone.utc).isoformat())
        return len(messages), hits, triaged

    def _since_timestamp(self, channel: str) -> datetime:
        raw = self._state.get(f"{POLL_KEY_PREFIX}{channel}")
        if raw:
            try:
                return datetime.fromisoformat(str(raw))
            except ValueError:
                pass
        return datetime.now(timezone.utc) - timedelta(minutes=cfg.poll_interval_minutes())

    def _dispatch_action_items(
        self,
        channel: str,
        thread_ts: str,
        message_ts: str,
        text: str,
        slack_user_id: str,
    ) -> dict[str, Any]:
        from company_brain.agents.operations.slack.action_items import ActionItemsAgent
        from company_brain.runtime import get_runtime

        return get_runtime().run(
            ActionItemsAgent,
            self.config,
            channel=channel,
            thread_ts=thread_ts,
            message_ts=message_ts,
            text=text,
            slack_user_id=slack_user_id,
        )
