"""Workstream sections of ``config/growth.yaml`` (activity, content, competitor, leads)."""

from __future__ import annotations

from typing import Any

from company_brain.config import load_yaml_config


def growth_cfg() -> dict[str, Any]:
    return load_yaml_config("growth")


def activity_cfg() -> dict[str, Any]:
    return dict(growth_cfg().get("activity") or {})


def content_cfg() -> dict[str, Any]:
    return dict(growth_cfg().get("content") or {})


def competitor_cfg() -> dict[str, Any]:
    return dict(growth_cfg().get("competitor") or {})


def leads_cfg() -> dict[str, Any]:
    return dict(growth_cfg().get("leads") or {})


def activity_poll_minutes() -> int:
    try:
        return max(5, int(activity_cfg().get("poll_interval_minutes", 30)))
    except (TypeError, ValueError):
        return 30


def content_poll_minutes() -> int:
    try:
        return max(15, int(content_cfg().get("poll_interval_minutes", 60)))
    except (TypeError, ValueError):
        return 60


def content_weekly_pull_weekday() -> int:
    """0=Monday … 6=Sunday."""
    try:
        return max(0, min(6, int(content_cfg().get("weekly_pull_weekday", 0))))
    except (TypeError, ValueError):
        return 0


def competitor_keywords() -> list[str]:
    raw = competitor_cfg().get("keywords") or []
    if isinstance(raw, list):
        return [str(k).strip() for k in raw if str(k).strip()]
    return []


def competitor_poll_minutes() -> int:
    try:
        return max(60, int(competitor_cfg().get("poll_interval_minutes", 360)))
    except (TypeError, ValueError):
        return 360


def leads_poll_minutes() -> int:
    try:
        return max(5, int(leads_cfg().get("poll_interval_minutes", 15)))
    except (TypeError, ValueError):
        return 15
