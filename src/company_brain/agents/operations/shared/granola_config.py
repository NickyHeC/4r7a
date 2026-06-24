"""Granola configuration helpers (``config/operations.yaml`` + env secrets)."""

from __future__ import annotations

import json
import os
from datetime import time
from typing import Any

from company_brain.agents.operations.shared.config import load_operations_config

_GRANOLA = "granola"


def granola_section() -> dict[str, Any]:
    return load_operations_config().get(_GRANOLA) or {}


def granola_mode() -> str:
    """``business`` (per-member API keys) or ``enterprise`` (single company-wide key)."""
    env_mode = os.getenv("GRANOLA_MODE", "").strip().lower()
    if env_mode in ("business", "enterprise"):
        return env_mode
    mode = (granola_section().get("mode") or "").strip().lower()
    if mode in ("business", "enterprise"):
        return mode
    if os.getenv("GRANOLA_API_KEY", "").strip():
        return "enterprise"
    if _parse_member_keys():
        return "business"
    return "business"


def ingest_time() -> time:
    raw = (granola_section().get("schedule") or {}).get("ingest_time", "18:00")
    hour, minute = raw.split(":")
    return time(int(hour), int(minute))


def workdays_only() -> bool:
    return bool((granola_section().get("schedule") or {}).get("workdays_only", True))


def backfill_days() -> int:
    onboarding = granola_section().get("onboarding") or {}
    return int(onboarding.get("backfill_days", 30))


def daily_wiki_path(day: str) -> str:
    """Wiki rel path for the compiled end-of-day digest (``YYYY-MM-DD``)."""
    template = (granola_section().get("wiki") or {}).get(
        "daily_digest", "operations/granola/daily/{date}.md"
    )
    return template.format(date=day)


def configured_members() -> list[dict[str, str]]:
    """Member roster for business mode (labels + emails; keys come from env)."""
    members = granola_section().get("members") or []
    out: list[dict[str, str]] = []
    for item in members:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("name") or "").strip()
        email = str(item.get("email") or "").strip()
        if label:
            out.append({"label": label, "email": email})
    return out


def _parse_member_keys() -> dict[str, str]:
    """Parse ``GRANOLA_MEMBER_KEYS`` → ``{label: api_key}``."""
    raw = os.getenv("GRANOLA_MEMBER_KEYS", "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items() if v}
        except json.JSONDecodeError:
            pass
    out: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        label, key = part.split(":", 1)
        label, key = label.strip(), key.strip()
        if label and key:
            out[label] = key
    return out


def member_api_keys() -> list[tuple[str, str, str]]:
    """Return ``(label, email, api_key)`` tuples for business mode."""
    keys = _parse_member_keys()
    roster = configured_members()
    if roster:
        out: list[tuple[str, str, str]] = []
        for member in roster:
            label = member["label"]
            key = keys.get(label) or os.getenv(f"GRANOLA_API_KEY_{label.upper()}", "").strip()
            if key:
                out.append((label, member.get("email", ""), key))
        return out
    return [(label, "", key) for label, key in keys.items()]


def enterprise_api_key() -> str:
    return os.getenv("GRANOLA_API_KEY", "").strip()


def granola_is_configured() -> bool:
    mode = granola_mode()
    if mode == "enterprise":
        return bool(enterprise_api_key())
    return bool(member_api_keys())
