"""Google Calendar configuration (``config/operations.yaml`` + env)."""

from __future__ import annotations

import os
from datetime import time
from typing import Any

from company_brain.agents.operations.shared.config import load_operations_config

_GCAL = "gcal"


def gcal_section() -> dict[str, Any]:
    return load_operations_config().get(_GCAL) or {}


def calendar_id() -> str:
    return str(gcal_section().get("calendar_id") or "primary")


def business_hours() -> tuple[time, time]:
    raw = gcal_section().get("business_hours") or {}
    start_h, start_m = str(raw.get("start", "09:00")).split(":")
    end_h, end_m = str(raw.get("end", "17:00")).split(":")
    return time(int(start_h), int(start_m)), time(int(end_h), int(end_m))


def timezone_name() -> str:
    return str((gcal_section().get("business_hours") or {}).get("timezone", "UTC"))


def default_duration_minutes() -> int:
    return int((gcal_section().get("meeting") or {}).get("default_duration_minutes", 30))


def proposal_slot_count() -> int:
    return int((gcal_section().get("meeting") or {}).get("slot_count", 3))


def meet_conference_enabled() -> bool:
    return bool((gcal_section().get("meeting") or {}).get("meet_conference", True))


def significant_event_min_minutes() -> int:
    return int(
        (gcal_section().get("significant_event") or {}).get("min_duration_minutes", 60)
    )


def significant_event_keywords() -> list[str]:
    raw = (gcal_section().get("significant_event") or {}).get("keywords") or []
    return [str(k).lower() for k in raw]


def daily_agenda_enabled() -> bool:
    env = os.getenv("GCAL_DAILY_AGENDA", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    return bool((gcal_section().get("daily_agenda") or {}).get("enabled", False))


def daily_agenda_time() -> time:
    raw = (gcal_section().get("daily_agenda") or {}).get("time", "08:00")
    hour, minute = raw.split(":")
    return time(int(hour), int(minute))


def daily_agenda_slack_user() -> str:
    return (
        os.getenv("GCAL_DAILY_AGENDA_SLACK_USER", "").strip()
        or str((gcal_section().get("daily_agenda") or {}).get("slack_user") or "")
    )


def oauth_access_token() -> str:
    return (
        os.getenv("GCAL_OAUTH_ACCESS_TOKEN", "").strip()
        or os.getenv("GMAIL_OAUTH_ACCESS_TOKEN", "").strip()
    )


def gcal_is_configured() -> bool:
    return bool(oauth_access_token()) or bool(os.getenv("GCAL_OAUTH_CLIENT_ID", "").strip())
