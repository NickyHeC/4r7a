"""Admin LLM-ops schedule helpers (from ``config/operations.yaml``)."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

import yaml

from company_brain.config import CONFIG_DIR

_DEFAULTS: dict[str, Any] = {
    "day": 1,
    "time": "09:00",
    "drift_ratio": 0.5,
    "verify_fail_rate": 0.3,
    "min_verify_samples": 5,
    "estimated_minutes": {
        "linear_stale_audit": 15,
    },
}


def load_operations_raw() -> dict[str, Any]:
    path = CONFIG_DIR / "operations.yaml"
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def llm_ops_config() -> dict[str, Any]:
    raw = load_operations_raw().get("admin") or {}
    block = dict(_DEFAULTS)
    nested = raw.get("llm_ops") or {}
    if isinstance(nested, dict):
        block.update({k: v for k, v in nested.items() if v is not None})
    mins = dict(_DEFAULTS["estimated_minutes"])
    mins.update(dict(block.get("estimated_minutes") or {}))
    block["estimated_minutes"] = mins
    return block


def parse_hhmm(value: str) -> time:
    try:
        hour, minute = str(value).strip().split(":", 1)
        return time(int(hour), int(minute))
    except (ValueError, TypeError):
        return time(9, 0)


def previous_month(*, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev = first - timedelta(days=1)
    return prev.strftime("%Y-%m")


def month_title(month: str) -> str:
    """``2026-07`` → ``Jul 2026``."""
    dt = datetime.strptime(month + "-01", "%Y-%m-%d")
    return dt.strftime("%b %Y")
