"""Typed helpers for ``config/operations.yaml`` gmail section."""

from __future__ import annotations

from datetime import time
from typing import Any

from company_brain.agents.operations.shared.config import load_operations_config


def gmail_cfg() -> dict[str, Any]:
    return load_operations_config().get("gmail") or {}


def mailbox_id() -> str:
    import os

    return os.getenv("GMAIL_MAILBOX", "").strip() or str(gmail_cfg().get("mailbox", "me"))


def schedules() -> dict[str, Any]:
    return gmail_cfg().get("schedules") or {}


def parse_times(values: list[str]) -> list[time]:
    out: list[time] = []
    for raw in values:
        hour, minute = raw.split(":", 1)
        out.append(time(int(hour), int(minute)))
    return out


def manager_times() -> list[time]:
    return parse_times(schedules().get("manager_times") or ["08:00", "12:00", "16:00"])


def sweep_time() -> time:
    raw = schedules().get("sweep_time", "22:00")
    hour, minute = raw.split(":", 1)
    return time(int(hour), int(minute))


def triage_interval_minutes() -> int:
    return int(schedules().get("triage_interval_minutes", 30))


def workdays_only() -> bool:
    return bool(schedules().get("workdays_only", True))


def backfill_days() -> int:
    onboarding = gmail_cfg().get("onboarding") or {}
    return int(onboarding.get("backfill_days", 30))


def label_defs() -> dict[str, Any]:
    return gmail_cfg().get("labels") or {}


def auto_archive_cold_tags() -> set[str]:
    tags: set[str] = set()
    for entry in label_defs().get("cold_inbound") or []:
        if entry.get("auto_archive"):
            tags.add(entry["name"])
    return tags


def wiki_paths() -> dict[str, str]:
    return gmail_cfg().get("wiki") or {}


def ingest_queue_path() -> str:
    return wiki_paths().get("ingest_queue", "operations/gmail/ingest-queue.md")


def timeline_path() -> str:
    return wiki_paths().get("timeline", "operations/decisions/timeline.md")


def attachments_dir() -> str:
    return wiki_paths().get("attachments_dir", "operations/gmail/attachments")


def investor_path() -> str:
    return gmail_cfg().get("investors_wiki") or wiki_paths().get(
        "investor",
        "operations/gmail/investor.md",
    )


def customer_path() -> str:
    return gmail_cfg().get("customer_wiki") or wiki_paths().get(
        "customer",
        "operations/gmail/customer.md",
    )


def customers_wiki_path() -> str:
    """Alias for :func:`customer_path` (legacy call sites)."""
    return customer_path()


def investor_interest_path() -> str:
    return wiki_paths().get("investor_interest", "operations/gmail/investor-interest.md")


def media_promotion_path() -> str:
    return wiki_paths().get("media_promotion", "operations/gmail/media-promotion.md")


def connection_path() -> str:
    return wiki_paths().get("connection", "operations/gmail/connection.md")


def inbound_candidate_path() -> str:
    return wiki_paths().get("inbound_candidate", "operations/gmail/inbound-candidate.md")


def vendor_dir() -> str:
    return wiki_paths().get("vendor_dir", "operations/gmail/vendor")


def partnership_digest_day() -> str:
    return str(schedules().get("partnership_digest_day", "friday")).lower()


def partnership_digest_time() -> time:
    raw = schedules().get("partnership_digest_time", "08:00")
    hour, minute = raw.split(":", 1)
    return time(int(hour), int(minute))


def thread_watcher_interval_minutes() -> int:
    return int(schedules().get("thread_watcher_interval_minutes", 15))


def ingest_review_day() -> str:
    return str(schedules().get("ingest_review_day", "monday")).lower()


def ingest_review_time() -> time:
    raw = schedules().get("ingest_review_time", "08:00")
    hour, minute = raw.split(":", 1)
    return time(int(hour), int(minute))


def slack_cfg() -> dict[str, Any]:
    return gmail_cfg().get("slack") or {}


def connected_mailboxes() -> list[str]:
    import os

    raw = os.getenv("GMAIL_CONNECTED_MAILBOXES", "").strip()
    if raw:
        return [m.strip() for m in raw.split(",") if m.strip()]
    boxes = gmail_cfg().get("connected_mailboxes") or []
    if boxes:
        return [str(m) for m in boxes]
    primary = os.getenv("GMAIL_MAILBOX", "").strip() or str(gmail_cfg().get("mailbox", "me"))
    return [primary]


def team_on_it_cfg() -> dict[str, Any]:
    return gmail_cfg().get("team_on_it") or {}


def team_on_it_slack_channel() -> str:
    return team_on_it_cfg().get("slack_channel") or "#team-ops"


def receipt_router_day() -> str:
    rr = gmail_cfg().get("receipt_router") or {}
    return str(rr.get("day", "friday")).lower()


def receipt_router_time() -> time:
    rr = gmail_cfg().get("receipt_router") or {}
    raw = rr.get("time", "08:00")
    hour, minute = raw.split(":", 1)
    return time(int(hour), int(minute))


def receipt_router_wiki_path() -> str:
    rr = gmail_cfg().get("receipt_router") or {}
    return rr.get("wiki_path", "operations/gmail/receipt-route.md")


def subscription_sender_domains() -> list[str]:
    rr = gmail_cfg().get("receipt_router") or {}
    return [str(d).lower() for d in (rr.get("subscription_senders") or [])]


def receipt_router_cfg() -> dict[str, Any]:
    return gmail_cfg().get("receipt_router") or {}


def receipt_company_domain() -> str:
    return str(receipt_router_cfg().get("company_domain") or "").strip().lower()


def receipt_destination_mailbox() -> str:
    """Inbox Ramp watches for auto-attaching receipts (default: primary mailbox)."""
    dest = receipt_router_cfg().get("destination_mailbox")
    if dest:
        return str(dest)
    return mailbox_id()


def receipt_forward_enabled() -> bool:
    return bool(receipt_router_cfg().get("forward_enabled", True))
