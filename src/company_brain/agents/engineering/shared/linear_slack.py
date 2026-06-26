"""Slack notification helpers for engineering Linear agents."""

from __future__ import annotations

from company_brain.agents.engineering.shared.linear_config import slack_channel
from company_brain.agents.operations.shared.operations_slack import channel_notifier
from company_brain.notify import Notifier


def linear_notifier() -> Notifier:
    """Severity-gated Notifier for the engineering Linear Slack channel."""
    return channel_notifier(slack_channel())
