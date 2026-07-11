"""Weave admin notifications."""

from __future__ import annotations

from company_brain.agents.operations.shared.operations_slack import channel_notifier
from company_brain.agents.operations.slack import slack_config as cfg
from company_brain.notify import Notifier


def weave_admin_notifier() -> Notifier:
    channel = cfg.weave_admin_channel()
    return channel_notifier(channel)
