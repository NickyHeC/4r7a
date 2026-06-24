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


def company_timeline_path() -> str:
    return wiki_paths().get("company_timeline", "operations/gmail/company-timeline.md")


def attachments_dir() -> str:
    return wiki_paths().get("attachments_dir", "operations/gmail/attachments")


def investors_crm_path() -> str:
    return gmail_cfg().get("investors_wiki") or wiki_paths().get(
        "investors_crm", "operations/gmail/investors-crm.md",
    )


def customers_wiki_path() -> str:
    return gmail_cfg().get("customers_wiki") or wiki_paths().get(
        "customer_crm", "operations/gmail/customer-crm.md",
    )


def investor_interests_path() -> str:
    return wiki_paths().get("investor_interests", "operations/gmail/investor-interests.md")


def media_promotion_path() -> str:
    return wiki_paths().get("media_promotion", "operations/gmail/media-promotion.md")


def company_connections_path() -> str:
    return wiki_paths().get("company_connections", "operations/gmail/company-connections.md")


def inbound_candidates_path() -> str:
    return wiki_paths().get("inbound_candidates", "operations/gmail/inbound-candidates.md")


def vendors_dir() -> str:
    return wiki_paths().get("vendors_dir", "operations/gmail/vendors")


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
    return rr.get("wiki_path", "operations/gmail/receipt-routing.md")


def subscription_sender_domains() -> list[str]:
    rr = gmail_cfg().get("receipt_router") or {}
    return [str(d).lower() for d in (rr.get("subscription_senders") or [])]
