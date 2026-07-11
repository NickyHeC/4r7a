"""Slack Channel Registry — maintain channel metadata and activity records.

Syncs Slack API channel list into ``config/slack_channels.json`` and auto-joins
internal channels when configured.

SDK: Neither (Slack SDK + config).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.slack import channels_config, slack_client


class ChannelRegistryAgent(BaseAgent):
    """Refresh Slack channel registry metadata."""

    name = "channel_registry"

    def should_run(self, **kwargs: Any) -> bool:
        return slack_client.slack_is_configured()

    def run(self, *, join_internal: bool = True, **kwargs: Any) -> dict[str, Any]:
        channels = slack_client.list_channels()
        synced = channels_config.sync_from_slack_api(channels)
        joined = slack_client.join_internal_channels() if join_internal else {"joined": 0}
        data = channels_config.load_channels_registry()
        return {
            "status": "ok",
            "channels": len(data.get("channels") or {}),
            "synced": synced,
            "joined": joined.get("joined", 0),
            "registry_path": str(channels_config.CHANNELS_FILE),
        }
