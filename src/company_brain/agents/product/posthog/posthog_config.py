"""PostHog platform configuration (``config/product.yaml`` → ``posthog``)."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from company_brain.config import load_yaml_config


def product_cfg() -> dict[str, Any]:
    return load_yaml_config("product")


def posthog_cfg() -> dict[str, Any]:
    return dict(product_cfg().get("posthog") or {})


def enabled() -> bool:
    return bool(posthog_cfg().get("enabled", True))


def timezone_name() -> str:
    return str(posthog_cfg().get("timezone") or "America/Los_Angeles").strip()


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name())
    except Exception:
        return ZoneInfo("America/Los_Angeles")


def run_weekday() -> int:
    raw = posthog_cfg().get("run_weekday", 0)
    try:
        return max(0, min(6, int(raw)))
    except (TypeError, ValueError):
        return 0


def run_hour() -> int:
    raw = posthog_cfg().get("run_hour", 9)
    try:
        return max(0, min(23, int(raw)))
    except (TypeError, ValueError):
        return 9


def run_minute() -> int:
    raw = posthog_cfg().get("run_minute", 0)
    try:
        return max(0, min(59, int(raw)))
    except (TypeError, ValueError):
        return 0


def min_exposures() -> int:
    raw = posthog_cfg().get("min_exposures", 100)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 100


def probability_threshold() -> float:
    raw = posthog_cfg().get("probability_threshold", 0.95)
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.95


def signup_funnel_cfg() -> dict[str, Any]:
    return dict(posthog_cfg().get("signup_funnel") or {})


def funnel_insight_name() -> str:
    return str(signup_funnel_cfg().get("funnel_insight_name") or "Landing to signup").strip()


def funnel_dashboard_name() -> str:
    return str(signup_funnel_cfg().get("dashboard_name") or "Signup").strip()


def landing_paths() -> list[str]:
    raw = signup_funnel_cfg().get("landing_paths") or ["/"]
    if not isinstance(raw, list):
        return ["/"]
    return [str(p).strip() or "/" for p in raw]


def signup_event() -> str:
    return str(signup_funnel_cfg().get("signup_event") or "user_signed_up").strip()


def product_channel() -> str:
    slack = product_cfg().get("slack") or {}
    return str(slack.get("product_channel") or "#product").strip() or "#product"
