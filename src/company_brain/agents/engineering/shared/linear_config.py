"""Typed helpers for ``config/engineering.yaml`` linear section."""

from __future__ import annotations

from typing import Any

from company_brain.agents.engineering.shared.config import load_engineering_config


def linear_cfg() -> dict[str, Any]:
    return load_engineering_config().get("linear") or {}


def team_id() -> str:
    return str(linear_cfg().get("team_id") or "").strip()


def team_key() -> str:
    return str(linear_cfg().get("team_key") or "").strip()


def default_priority() -> int | None:
    val = linear_cfg().get("default_priority")
    return int(val) if val is not None else None


def poll_interval_minutes() -> int:
    val = linear_cfg().get("poll_interval_minutes")
    try:
        return max(5, int(val))
    except (TypeError, ValueError):
        return 30


def slot_check_cfg() -> dict:
    return dict(linear_cfg().get("slot_check") or {})


def task_class_fan_out(task_class: str) -> list[str]:
    classes = linear_cfg().get("task_classes") or {}
    entry = classes.get(task_class) or {}
    fan_out = entry.get("fan_out")
    if isinstance(fan_out, list) and fan_out:
        return [str(p) for p in fan_out]
    return ["linear"]


def stale_audit_cfg() -> dict[str, Any]:
    return dict(linear_cfg().get("stale_audit") or {})


def manual_cfg() -> dict[str, Any]:
    return dict(linear_cfg().get("manual") or {})


def slack_channel() -> str:
    return str(linear_cfg().get("slack_channel") or "#team-ops").strip()
