"""Slack notification helpers for growth department agents."""

from __future__ import annotations

from company_brain.agents.growth.discord import discord_config as growth_cfg
from company_brain.agents.operations.shared.operations_slack import (
    channel_notifier,
    growth_notifier,
)
from company_brain.notify import Notifier


def discord_review_notifier() -> Notifier:
    """Notifier for draft Discord replies awaiting human review."""
    return channel_notifier(growth_cfg.slack_discord_channel())


__all__ = ["discord_review_notifier", "growth_notifier"]
