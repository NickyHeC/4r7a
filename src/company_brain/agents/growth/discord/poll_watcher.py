"""Discord poll watcher — REST backup for Gateway ingest triage.

SDK: Neither (Discord REST + orchestration).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.growth.discord import channels_config, discord_client
from company_brain.agents.growth.discord.ingest_triage import IngestTriageAgent
from company_brain.config import AppConfig

POLL_KEY_PREFIX = "discord_poll_watch:"


class PollWatcherAgent(BaseAgent):
    """Poll Discord text channels and run ingest triage (Gateway backup)."""

    name = "discord_poll_watcher"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()
        self._triage = IngestTriageAgent(config, **kwargs)

    def should_run(self, **kwargs: Any) -> bool:
        return discord_client.discord_is_configured()

    def run(self, **kwargs: Any) -> dict[str, Any]:
        scanned = 0
        triaged = 0
        for channel in channels_config.list_text_channels():
            channel_id = str(channel.get("id") or "")
            if not channel_id:
                continue
            count, hits = self._scan_channel(channel_id)
            scanned += count
            triaged += hits
        return {
            "channels": len(channels_config.list_text_channels()),
            "messages": scanned,
            "triaged": triaged,
        }

    def _scan_channel(self, channel_id: str) -> tuple[int, int]:
        since = self._since_timestamp(channel_id)
        after = discord_client.datetime_to_snowflake_after(since) if since else None
        try:
            messages = discord_client.fetch_channel_messages(channel_id, after=after, limit=100)
        except discord_client.DiscordClientError:
            self.logger.exception("Discord fetch failed for %s", channel_id)
            return 0, 0

        hits = 0
        for msg in messages:
            result = self._triage.process_message(
                channel_id,
                msg,
                channel_type=int((channels_config.get_channel(channel_id) or {}).get("type", 0)),
            )
            if result.get("status") == "routed":
                hits += 1

        if messages:
            latest = messages[0]
            ts = latest.get("timestamp")
            if ts:
                try:
                    stamp = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
                    self._state.set(f"{POLL_KEY_PREFIX}{channel_id}", stamp)
                except ValueError:
                    pass
        return len(messages), hits

    def _since_timestamp(self, channel_id: str) -> datetime | None:
        raw = self._state.get(f"{POLL_KEY_PREFIX}{channel_id}")
        if raw is None:
            return datetime.now(timezone.utc) - timedelta(hours=24)
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (TypeError, ValueError):
            return datetime.now(timezone.utc) - timedelta(hours=24)
