"""Google Ads platform configuration (``config/growth.yaml`` → ``google_ads``)."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from company_brain.config import load_yaml_config


def growth_cfg() -> dict[str, Any]:
    return load_yaml_config("growth")


def google_ads_cfg() -> dict[str, Any]:
    return dict(growth_cfg().get("google_ads") or {})


def enabled() -> bool:
    return bool(google_ads_cfg().get("enabled", True))


def timezone_name() -> str:
    return str(google_ads_cfg().get("timezone") or "America/Los_Angeles").strip()


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name())
    except Exception:
        return ZoneInfo("America/Los_Angeles")


def pacing_alert_threshold() -> float:
    """Fraction of period budget spent that triggers an actionable alert (0–1)."""
    raw = google_ads_cfg().get("pacing_alert_threshold", 0.9)
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.9


def run_weekday() -> int:
    """0=Monday … 6=Sunday. Default Monday."""
    raw = google_ads_cfg().get("run_weekday", 0)
    try:
        return max(0, min(6, int(raw)))
    except (TypeError, ValueError):
        return 0


def run_hour() -> int:
    raw = google_ads_cfg().get("run_hour", 8)
    try:
        return max(0, min(23, int(raw)))
    except (TypeError, ValueError):
        return 8


def run_minute() -> int:
    raw = google_ads_cfg().get("run_minute", 0)
    try:
        return max(0, min(59, int(raw)))
    except (TypeError, ValueError):
        return 0


def cpa_lookback_days() -> int:
    raw = google_ads_cfg().get("cpa_lookback_days", 30)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 30
