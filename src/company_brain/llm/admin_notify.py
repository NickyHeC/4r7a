"""Admin Slack notifier for LLM / wiki operations."""

from __future__ import annotations

from company_brain.agents.operations.shared.operations_slack import channel_notifier
from company_brain.config import load_models_config
from company_brain.notify import Notifier


def wiki_admin_channel() -> str:
    cfg = load_models_config()
    return cfg.token_budget.admin_channel or "#wiki-admin"


def wiki_admin_notifier() -> Notifier:
    return channel_notifier(wiki_admin_channel())
