"""Discord Gateway event router — MESSAGE_CREATE dispatch to ingest triage."""

from __future__ import annotations

import logging
from typing import Any

from company_brain.agents.growth.discord import channels_config, discord_client
from company_brain.agents.growth.discord.ingest_triage import IngestTriageAgent
from company_brain.config import AppConfig

logger = logging.getLogger(__name__)


class DiscordEventsRouter:
    """Route Discord Gateway payloads to platform specialists."""

    def __init__(self, config: AppConfig):
        self.config = config

    def handle_dispatch(self, event_type: str | None, data: dict[str, Any]) -> dict[str, Any]:
        if event_type == "MESSAGE_CREATE":
            return self._handle_message_create(data)
        if event_type == "THREAD_CREATE":
            return self._handle_thread_create(data)
        return {"status": "ignored", "reason": event_type or "unknown"}

    def _handle_message_create(self, event: dict[str, Any]) -> dict[str, Any]:
        channel_id = str(event.get("channel_id") or "")
        if not channel_id:
            return {"status": "skipped", "reason": "no_channel"}

        channel_type = int((event.get("channel") or {}).get("type", -1))
        if channel_type < 0:
            meta = channels_config.get_channel(channel_id) or {}
            channel_type = int(meta.get("type", 0))

        if channels_config.is_out_of_scope(channel_id):
            return {"status": "skipped", "reason": "out_of_scope"}
        parent = str((event.get("channel") or {}).get("parent_id") or "")
        if parent and channels_config.is_out_of_scope(parent):
            return {"status": "skipped", "reason": "parent_out_of_scope"}

        agent = IngestTriageAgent(self.config)
        return agent.process_message(channel_id, event, channel_type=channel_type)

    def _handle_thread_create(self, event: dict[str, Any]) -> dict[str, Any]:
        channel_id = str(event.get("id") or "")
        if not channel_id:
            return {"status": "skipped", "reason": "no_channel"}
        channels_config.upsert_channel(
            channel_id,
            name=str(event.get("name") or channel_id),
            type=int(event.get("type", 11)),
            parent_id=str(event.get("parent_id") or ""),
        )
        return {"status": "thread_registered", "channel_id": channel_id}


def sync_guild_channels(guild_id: str) -> dict[str, int]:
    """Refresh ``config/discord_channels.json`` from the Discord API."""
    if not guild_id:
        return {"synced": 0}
    channels = discord_client.list_guild_channels(guild_id)
    count = channels_config.sync_from_discord_api(channels)
    return {"synced": count}
