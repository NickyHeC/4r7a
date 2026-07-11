"""Slack platform configuration (``config/operations.yaml`` → ``slack_platform``)."""

from __future__ import annotations

from typing import Any

from company_brain.agents.operations.shared.config import load_operations_config

ATTENTION_ACTION = "1. Action"
ATTENTION_REPLY = "2. Reply"
ATTENTION_FYI = "3. FYI"
ATTENTION_TEAM = "4. Team On It"


def slack_platform_cfg() -> dict[str, Any]:
    return load_operations_config().get("slack_platform") or {}


def poll_interval_minutes() -> int:
    raw = slack_platform_cfg().get("poll_interval_minutes", 30)
    try:
        return max(5, int(raw))
    except (TypeError, ValueError):
        return 30


def workdays_only() -> bool:
    return bool(slack_platform_cfg().get("workdays_only", True))


def watched_channels() -> list[str]:
    channels = slack_platform_cfg().get("watched_channels") or []
    if isinstance(channels, list) and channels:
        return [str(c).strip() for c in channels if str(c).strip()]
    return ["#team-ops"]


def action_keywords() -> list[str]:
    defaults = ["action item", "todo", "to-do", "follow up", "follow-up", "will do", "assigned to"]
    raw = slack_platform_cfg().get("action_keywords")
    if isinstance(raw, list) and raw:
        return [str(k).lower() for k in raw]
    return defaults


def events_cfg() -> dict[str, Any]:
    return dict(slack_platform_cfg().get("events") or {})


def events_mode() -> str:
    mode = str(events_cfg().get("mode") or "socket").strip().lower()
    return mode if mode in {"socket", "http"} else "socket"


def events_http_path() -> str:
    return str(events_cfg().get("http_path") or "/slack/events/wiki")


def debounce_minutes() -> int:
    raw = slack_platform_cfg().get("debounce_minutes", 3)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 3


def reaction_names(kind: str) -> list[str]:
    reactions = slack_platform_cfg().get("reactions") or {}
    defaults = {
        "acknowledge": ["thumbsup", "ok_hand"],
        "done": ["white_check_mark"],
    }
    raw = reactions.get(kind) or defaults.get(kind) or []
    if isinstance(raw, list):
        return [str(r).strip() for r in raw if str(r).strip()]
    return defaults.get(kind, [])


def slack_is_configured() -> bool:
    from company_brain.agents.operations.slack import slack_client

    return slack_client.slack_is_configured()
