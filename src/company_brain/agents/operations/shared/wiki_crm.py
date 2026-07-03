"""Wiki CRM helpers — seed pages, append entries, format mail sections."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import (
    customers_wiki_path,
    investor_path,
)
from company_brain.agents.operations.shared.mail_body import plain_text
from company_brain.agents.operations.shared.routing import RoutingRecord
from company_brain.config import resolve_wiki_dir
from company_brain.wiki.publish import APPEND, UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

CRM_SEEDS: list[tuple[str, str, str, str]] = [
    (
        investor_path(),
        "Investors",
        "# Investors\n\nConfirmed investors (email or domain, one per line):\n\n- example-vc.com\n",
        "investor",
    ),
    (
        customers_wiki_path(),
        "Customers",
        "# Customers\n\nActive customers (email or domain, one per line):\n\n",
        "customer",
    ),
]


def ensure_crm_seeds(mailbox: str | None = None) -> int:
    """Create empty CRM wiki pages if missing. Returns count created."""
    from company_brain.agents.operations.shared.profiles import crm_seed_keys_for_profile
    from company_brain.crm.registry import rebuild_registry
    from company_brain.crm.seeds import ensure_crm_seeds as ensure_crm_structure

    allowed = crm_seed_keys_for_profile(mailbox)
    created = ensure_crm_structure()
    store = LocalWikiStore(root=resolve_wiki_dir())
    for rel_path, title, body, key in CRM_SEEDS:
        if key not in allowed:
            continue
        if store.exists(rel_path):
            continue
        write_wiki_page(rel_path, title, body, mode=UPDATE, section="crm", sync=False)
        created += 1
    rebuild_registry()
    return created


def format_mail_section(
    record: RoutingRecord, message: dict[str, Any], *, max_body: int = 2500
) -> str:
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


def append_crm_entry(rel_path: str, title: str, section: str, *, section_key: str = "crm") -> None:
    write_wiki_page(rel_path, title, section, mode=APPEND, section=section_key, sync=False)
