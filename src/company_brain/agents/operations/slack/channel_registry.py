"""Slack Channel Registry — maintain channel metadata and activity records.

Specialist dispatched by ``slack_manager`` (daily). Session 1 skeleton: ensures
``config/slack_channels.json`` exists and reports channel count.

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

    def run(self, **kwargs: Any) -> dict[str, Any]:
        data = channels_config.load_channels_registry()
        channels = data.get("channels") or {}
        return {
            "status": "ok",
            "channels": len(channels),
            "registry_path": str(channels_config.CHANNELS_FILE),
        }
