"""Workstream sections of ``config/product.yaml``."""

from __future__ import annotations

from typing import Any

from company_brain.config import load_yaml_config


def product_cfg() -> dict[str, Any]:
    return load_yaml_config("product")


def _section(name: str) -> dict[str, Any]:
    return dict(product_cfg().get(name) or {})


def update_cfg() -> dict[str, Any]:
    return _section("update")


def use_case_cfg() -> dict[str, Any]:
    return _section("use_case")


def docs_cfg() -> dict[str, Any]:
    return _section("docs")


def progress_cfg() -> dict[str, Any]:
    return _section("progress")


def attribution_cfg() -> dict[str, Any]:
    return _section("attribution")


def _poll(section: dict[str, Any], default: int, *, minimum: int = 15) -> int:
    try:
        return max(minimum, int(section.get("poll_interval_minutes", default)))
    except (TypeError, ValueError):
        return default


def update_poll_minutes() -> int:
    return _poll(update_cfg(), 360, minimum=60)


def use_case_poll_minutes() -> int:
    return _poll(use_case_cfg(), 360, minimum=60)


def docs_poll_minutes() -> int:
    return _poll(docs_cfg(), 360, minimum=60)


def progress_poll_minutes() -> int:
    return _poll(progress_cfg(), 360, minimum=60)


def attribution_poll_minutes() -> int:
    return _poll(attribution_cfg(), 180, minimum=30)


def update_run_day() -> int:
    try:
        return max(1, min(28, int(update_cfg().get("run_day", 1))))
    except (TypeError, ValueError):
        return 1


def docs_base_url() -> str:
    return str(docs_cfg().get("base_url") or "").strip().rstrip("/")


def docs_proprietary_patterns() -> list[str]:
    raw = docs_cfg().get("proprietary_patterns") or []
    if isinstance(raw, list):
        return [str(p).strip().lower() for p in raw if str(p).strip()]
    return []


def signup_source_cfg() -> dict[str, Any]:
    return dict(attribution_cfg().get("signup_source") or {})


def usage_drop_cfg() -> dict[str, Any]:
    posthog = dict(product_cfg().get("posthog") or {})
    return dict(posthog.get("usage_drop") or {})
