"""Slack notification helpers for product department agents."""

from __future__ import annotations

from company_brain.agents.operations.shared.operations_slack import channel_notifier
from company_brain.agents.product.posthog import posthog_config as cfg
from company_brain.notify import Notifier


def product_notifier() -> Notifier:
    """Severity-gated Notifier bound to the product Slack channel."""
    return channel_notifier(cfg.product_channel())


__all__ = ["product_notifier"]
