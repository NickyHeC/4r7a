"""Growth / Discord platform configuration (``config/growth.yaml``)."""

from __future__ import annotations

from typing import Any

from company_brain.config import load_yaml_config

ATTENTION_ACTION = "1. Action"
ATTENTION_REPLY = "2. Reply"
ATTENTION_FYI = "3. FYI"

# Discord channel types (API v10)
CHANNEL_GUILD_TEXT = 0
CHANNEL_PUBLIC_THREAD = 11
CHANNEL_PRIVATE_THREAD = 12
CHANNEL_ANNOUNCEMENT = 5
CHANNEL_GUILD_FORUM = 15

THREAD_CHANNEL_TYPES = {CHANNEL_PUBLIC_THREAD, CHANNEL_PRIVATE_THREAD}


def growth_cfg() -> dict[str, Any]:
    return load_yaml_config("growth")


def discord_cfg() -> dict[str, Any]:
    return dict(growth_cfg().get("discord") or {})


def guild_id() -> str:
    return str(discord_cfg().get("guild_id") or "").strip()


def poll_interval_minutes() -> int:
    raw = discord_cfg().get("poll_interval_minutes", 15)
    try:
        return max(5, int(raw))
    except (TypeError, ValueError):
        return 15


def workdays_only() -> bool:
    return bool(discord_cfg().get("workdays_only", False))


def exclude_channels() -> list[str]:
    raw = discord_cfg().get("exclude_channels") or []
    if isinstance(raw, list):
        return [str(c).strip().lower().lstrip("#") for c in raw if str(c).strip()]
    return []


def onboarding_default_backfill_days() -> int:
    raw = discord_cfg().get("onboarding_default_backfill_days", 30)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 30


def member_scoring_min_messages() -> int:
    raw = discord_cfg().get("member_scoring_min_messages", 3)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 3


def interesting_score_threshold() -> int:
    raw = discord_cfg().get("interesting_score_threshold", 4)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 4


def absorb_batch_hour_utc() -> int:
    raw = discord_cfg().get("absorb_batch_hour_utc", 6)
    try:
        return max(0, min(23, int(raw)))
    except (TypeError, ValueError):
        return 6


def slack_discord_channel() -> str:
    slack = growth_cfg().get("slack") or {}
    return str(slack.get("discord_channel") or "#discord")


def debounce_minutes() -> int:
    raw = discord_cfg().get("debounce_minutes", 3)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 3


def gateway_intents() -> int:
    """GUILDS | GUILD_MESSAGES | MESSAGE_CONTENT."""
    raw = discord_cfg().get("gateway_intents")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    return (1 << 0) | (1 << 9) | (1 << 15)
