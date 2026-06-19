"""Typed helpers for ``config/operations.yaml`` linear section."""

from __future__ import annotations

from datetime import time
from typing import Any

from company_brain.agents.operations.shared.config import load_operations_config


def linear_cfg() -> dict[str, Any]:
    return load_operations_config().get("linear") or {}


def team_id() -> str:
    return str(linear_cfg().get("team_id") or "").strip()


def team_key() -> str:
    return str(linear_cfg().get("team_key") or "").strip()


def default_priority() -> int | None:
    val = linear_cfg().get("default_priority")
    return int(val) if val is not None else None


def team_on_it_cfg() -> dict[str, Any]:
    return load_operations_config().get("gmail", {}).get("team_on_it") or {}


def team_on_it_slack_channel() -> str:
    return team_on_it_cfg().get("slack_channel") or "#team-ops"


def connected_mailboxes() -> list[str]:
    import os

    raw = os.getenv("GMAIL_CONNECTED_MAILBOXES", "").strip()
    if raw:
        return [m.strip() for m in raw.split(",") if m.strip()]
    cfg = load_operations_config().get("gmail") or {}
    boxes = cfg.get("connected_mailboxes") or []
    if boxes:
        return [str(m) for m in boxes]
    primary = os.getenv("GMAIL_MAILBOX", "").strip() or str(cfg.get("mailbox", "me"))
    return [primary]


def receipt_router_day() -> str:
    rr = load_operations_config().get("gmail", {}).get("receipt_router") or {}
    return str(rr.get("day", "friday")).lower()


def receipt_router_time() -> time:
    rr = load_operations_config().get("gmail", {}).get("receipt_router") or {}
    raw = rr.get("time", "08:00")
    hour, minute = raw.split(":", 1)
    return time(int(hour), int(minute))


def receipt_router_wiki_path() -> str:
    rr = load_operations_config().get("gmail", {}).get("receipt_router") or {}
    return rr.get("wiki_path", "operations/gmail/receipt-routing.md")


def subscription_sender_domains() -> list[str]:
    rr = load_operations_config().get("gmail", {}).get("receipt_router") or {}
    return [str(d).lower() for d in (rr.get("subscription_senders") or [])]
