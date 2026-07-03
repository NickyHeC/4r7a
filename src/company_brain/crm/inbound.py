"""CRM inbound item pages — write typed inbound MD + optional contact dual-write."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.mail_body import plain_text
from company_brain.agents.operations.shared.routing import RoutingRecord
from company_brain.crm.config import inbound_type_dir
from company_brain.crm.contacts import append_contact_interaction
from company_brain.crm.registry import lookup_contact
from company_brain.crm.slug import slug_from_email
from company_brain.wiki.publish import UPDATE, write_wiki_page

TRIAGE_TAG_TO_INBOUND: dict[str, str] = {
    "Cold Inbound/Press & Podcast": "press-podcast",
    "Cold Inbound/Event Invitations": "event-invitation",
    "Cold Inbound/Partnership": "partnership",
    "Cold Inbound/Founder Networking": "founder-networking",
    "Cold Inbound/Investor Interest": "investor-interest",
    "Cold Inbound/Job Seekers": "candidate",
}

INBOUND_TAGS = frozenset(TRIAGE_TAG_TO_INBOUND)


def inbound_type_for_record(record: RoutingRecord) -> str | None:
    for tag in record.domain_tags:
        if tag in TRIAGE_TAG_TO_INBOUND:
            return TRIAGE_TAG_TO_INBOUND[tag]
    return None


def inbound_slug(record: RoutingRecord, subject: str) -> str:
    date_part = _date_token(record.triaged_at)
    subject_part = _slugify(subject) or record.message_id[:12]
    return f"{date_part}-{subject_part}"


def write_inbound_item(
    record: RoutingRecord,
    message: dict[str, Any],
    *,
    inbound_type: str,
    score: int,
    score_reasons: list[str],
    slack_notified: bool = False,
) -> str:
    """Write inbound MD page; append interaction on contact when known."""
    subject = record.extracted.get("subject") or rest.message_subject_from(message)
    from_ = record.extracted.get("from") or rest.message_from(message)
    received = record.extracted.get("date") or rest.message_date(message) or record.triaged_at
    preview = plain_text(message, max_chars=2500).strip()

    entry = lookup_contact(from_)
    contact_slug = entry.slug if entry else ""
    slug = inbound_slug(record, subject)
    rel = f"{inbound_type_dir(inbound_type)}/{slug}.md"

    body = (
        f"**From:** {from_}\n\n"
        f"**Subject:** {subject}\n\n"
        f"**Received:** {received}\n\n"
        f"**Score:** {score}\n\n"
        f"**Gmail message:** `{record.message_id}`\n\n"
        f"**Thread:** `{record.thread_id}`\n\n"
        f"{preview}\n"
    )

    extra = {
        "inbound_type": inbound_type,
        "contact_slug": contact_slug,
        "message_id": record.message_id,
        "thread_id": record.thread_id,
        "mailbox": record.mailbox,
        "triaged_at": record.triaged_at,
        "received_at": received,
        "score": score,
        "score_reasons": score_reasons,
        "slack_notified": slack_notified,
        "status": "open",
    }
    write_wiki_page(
        rel,
        subject,
        body,
        mode=UPDATE,
        section="crm",
        extra_frontmatter=extra,
        sync=False,
    )

    if contact_slug:
        section = (
            f"## {subject} — {_date_token(record.triaged_at)}\n\n"
            f"**Type:** {inbound_type} · **Score:** {score}\n\n"
            f"**From:** {from_}\n\n"
            f"**Message:** `{record.message_id}`\n\n"
            f"{preview[:800]}\n"
        )
        append_contact_interaction(contact_slug, section)

    return rel


def contact_slug_from_from(from_hdr: str) -> str:
    """Derive slug from From header when registry has no entry (unused write path)."""
    match = re.search(r"<([^>]+)>", from_hdr)
    email = (match.group(1) if match else from_hdr).strip()
    if "@" in email:
        return slug_from_email(email)
    return _slugify(from_hdr) or "unknown"


def _date_token(iso_ts: str) -> str:
    if not iso_ts:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        return iso_ts[:10]
    except (TypeError, IndexError):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48]


def mark_inbound_status_for_thread(thread_id: str, status: str) -> int:
    """Update inbound item pages matching ``thread_id`` (returns count updated)."""
    from company_brain.config import resolve_wiki_dir
    from company_brain.crm.config import INBOUND_TYPES, inbound_type_dir
    from company_brain.wiki.store import LocalWikiStore

    store = LocalWikiStore(root=resolve_wiki_dir())
    updated = 0
    for inbound_type in INBOUND_TYPES:
        if inbound_type == "unmatched":
            continue
        prefix = inbound_type_dir(inbound_type) + "/"
        for rel in store.list(prefix):
            if not rel.endswith(".md"):
                continue
            doc = store.read(rel)
            if str(doc.frontmatter.get("thread_id") or "") != thread_id:
                continue
            doc.frontmatter["status"] = status
            write_wiki_page(
                rel,
                str(doc.frontmatter.get("title") or rel),
                doc.body,
                mode=UPDATE,
                section="crm",
                extra_frontmatter=doc.frontmatter,
                sync=False,
            )
            updated += 1
    return updated
