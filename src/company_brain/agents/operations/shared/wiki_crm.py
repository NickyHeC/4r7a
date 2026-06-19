"""Wiki CRM helpers — seed pages, append entries, format mail sections."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import (
    company_connections_path,
    customer_crm_path,
    inbound_candidates_path,
    investor_interests_path,
    investors_crm_path,
    media_promotion_path,
)
from company_brain.agents.operations.shared.mail_body import plain_text
from company_brain.agents.operations.shared.routing import RoutingRecord
from company_brain.config import resolve_wiki_dir
from company_brain.wiki.publish import APPEND, UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

CRM_SEEDS: list[tuple[str, str, str]] = [
    (
        investors_crm_path(),
        "Investors CRM",
        "# Investors CRM\n\n"
        "Confirmed investors (email or domain, one per line):\n\n"
        "- example-vc.com\n",
    ),
    (
        investor_interests_path(),
        "Investor Interests",
        "# Investor Interests\n\n"
        "Cold inbound investor interest appended below (newest first).\n",
    ),
    (
        customer_crm_path(),
        "Customer CRM",
        "# Customer CRM\n\n"
        "Active customers (email or domain, one per line):\n\n",
    ),
    (
        media_promotion_path(),
        "Media Promotion",
        "# Media Promotion\n\n"
        "Press and podcast inbound (newest first).\n",
    ),
    (
        company_connections_path(),
        "Company Connections",
        "# Company Connections\n\n"
        "People and warm connections (newest first). Excludes investors.\n",
    ),
    (
        inbound_candidates_path(),
        "Inbound Candidates",
        "# Inbound Candidates\n\n"
        "Job seeker inbound (newest first).\n",
    ),
]


def ensure_gmail_crm_seeds() -> int:
    """Create empty CRM wiki pages if missing. Returns count created."""
    store = LocalWikiStore(root=resolve_wiki_dir())
    created = 0
    for rel_path, title, body in CRM_SEEDS:
        if store.exists(rel_path):
            continue
        write_wiki_page(rel_path, title, body, mode=UPDATE, section="operations/gmail")
        created += 1
    return created


def format_mail_section(record: RoutingRecord, message: dict[str, Any], *, max_body: int = 2500) -> str:
    subject = record.extracted.get("subject") or rest.message_subject_from(message)
    from_ = record.extracted.get("from") or rest.message_from(message)
    date = record.extracted.get("date") or rest.message_date(message) or ""
    body = plain_text(message, max_chars=max_body).strip()
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        f"## {subject} — {when}\n\n"
        f"**From:** {from_}\n\n"
        f"**Date:** {date}\n\n"
        f"**Message:** `{record.message_id}`\n\n"
        f"{body}\n"
    )


def append_crm_entry(rel_path: str, title: str, section: str) -> None:
    write_wiki_page(rel_path, title, section, mode=APPEND, section="operations/gmail")
