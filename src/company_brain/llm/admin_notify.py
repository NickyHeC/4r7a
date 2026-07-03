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


def wiki_eval_notifier(channel: str | None = None) -> Notifier:
    """Notifier for LLM vibe-eval spot checks (default ``#wiki``)."""
    return channel_notifier(channel or spot_check_channel())


def spot_check_channel() -> str:
    cfg = load_models_config()
    spec = getattr(cfg, "eval_spotcheck", None)
    if spec is not None and getattr(spec, "channel", None):
        return spec.channel
    return "#wiki"
