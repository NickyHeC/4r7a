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
