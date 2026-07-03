"""CRM promotion — two-way exchange detection and connection auto-promote."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.decision import NON_DECISION_PATTERNS
from company_brain.agents.operations.shared.mail_body import plain_text
from company_brain.agents.operations.shared.routing import RoutingRecord, RoutingStore
from company_brain.crm.config import default_connection_employee, promotion_log_path
from company_brain.crm.contacts import (
    display_name_from_from_header,
    email_from_from_header,
    read_contact,
    write_contact,
)
from company_brain.crm.inbound import (
    INBOUND_TAGS,
    inbound_type_for_record,
    mark_inbound_status_for_thread,
)
from company_brain.crm.registry import lookup_contact, rebuild_registry
from company_brain.crm.schema import ContactEntity
from company_brain.crm.slug import slug_from_email
from company_brain.wiki.publish import APPEND, format_append_section, write_wiki_page

logger = logging.getLogger(__name__)

EXTRA_DISMISSIVE = (
    r"\bunsubscribe\b",
    r"\bno thank",
    r"\bnot interested\b",
    r"\bpass on\b",
    r"\bdecline\b",
)

PROTECTED_SEGMENTS = frozenset({"customer", "investor"})


def is_dismissive_outbound(message: dict[str, Any]) -> bool:
    """True when a sent message is a thanks/pass/not-interested style reply."""
    text = plain_text(message, max_chars=4000).strip().lower()
    normalized = re.sub(r"\s+", " ", text).strip()
    for pat in NON_DECISION_PATTERNS + EXTRA_DISMISSIVE:
        if re.search(pat, normalized):
            return True
    return False


def thread_is_two_way(thread: dict[str, Any], *, mailbox: str) -> bool:
    me = rest.mailbox_email(mailbox)
    has_inbound = False
    has_outbound = False
    for msg in thread.get("messages") or []:
        labels = msg.get("labelIds") or []
        from_hdr = rest.message_from(msg).lower()
        if "SENT" in labels or (me and me in from_hdr):
            has_outbound = True
        elif not me or me not in from_hdr:
            has_inbound = True
    return has_inbound and has_outbound


def external_from_thread(thread: dict[str, Any], *, mailbox: str) -> str:
    """From header of the first non-sent message in the thread."""
    me = rest.mailbox_email(mailbox)
    for msg in thread.get("messages") or []:
        labels = msg.get("labelIds") or []
        if "SENT" in labels:
            continue
        from_hdr = rest.message_from(msg)
        if me and me in from_hdr.lower():
            continue
        if from_hdr:
            return from_hdr
    return ""


def thread_has_crm_inbound(records: list[RoutingRecord]) -> bool:
    return any(INBOUND_TAGS.intersection(rec.domain_tags) for rec in records)


def thread_already_promoted(records: list[RoutingRecord]) -> bool:
    return any(rec.extracted.get("crm_promoted_to") for rec in records)


def try_promote_thread_on_sent(
    *,
    mailbox: str,
    thread_id: str,
    sent_message: dict[str, Any],
    store: RoutingStore | None = None,
) -> dict[str, Any]:
    """After a non-dismissive sent reply, promote cold inbound counterparty to connection."""
    store = store or RoutingStore()
    records = store.find_by_thread(mailbox, thread_id)
    if not records or not thread_has_crm_inbound(records):
        return {"promoted": False, "reason": "no_crm_inbound"}
    if thread_already_promoted(records):
        return {"promoted": False, "reason": "already_promoted"}

    if is_dismissive_outbound(sent_message):
        _mark_thread_engaged(store, records, status="archived")
        mark_inbound_status_for_thread(thread_id, "archived")
        return {"promoted": False, "reason": "dismissive_outbound"}

    thread = rest.get_thread(thread_id, mailbox=mailbox)
    if not thread_is_two_way(thread, mailbox=mailbox):
        return {"promoted": False, "reason": "not_two_way"}

    from_hdr = external_from_thread(thread, mailbox=mailbox)
    email = email_from_from_header(from_hdr)
    if not email:
        return {"promoted": False, "reason": "no_counterparty_email"}

    entry = lookup_contact(from_hdr)
    if entry and entry.segment in PROTECTED_SEGMENTS:
        _mark_thread_engaged(store, records, status="engaged")
        mark_inbound_status_for_thread(thread_id, "engaged")
        return {"promoted": False, "reason": f"protected_segment:{entry.segment}"}

    slug = entry.slug if entry else slug_from_email(email)
    entity = read_contact(slug)
    if entity and entity.segment in PROTECTED_SEGMENTS:
        _mark_thread_engaged(store, records, status="engaged")
        mark_inbound_status_for_thread(thread_id, "engaged")
        return {"promoted": False, "reason": f"protected_segment:{entity.segment}"}

    promoted_from = _promoted_from_label(records)
    prior_segment = entity.segment if entity else "inbound"
    now = datetime.now(timezone.utc).date().isoformat()

    if entity:
        entity.segment = "connection"
        entity.promoted_from = promoted_from
        entity.promoted_at = now
        if not entity.main_connection_employee:
            entity.main_connection_employee = default_connection_employee()
    else:
        employee = default_connection_employee()
        if not employee:
            logger.warning("CRM promotion skipped: crm.default_connection_employee not set")
            return {"promoted": False, "reason": "missing_default_connection_employee"}
        entity = ContactEntity(
            slug=slug,
            title=display_name_from_from_header(from_hdr),
            segment="connection",
            canonical_email=email,
            main_connection_employee=employee,
            promoted_from=promoted_from,
            promoted_at=now,
        )

    write_contact(entity, rebuild=True)
    _append_promotion_log(
        slug=slug,
        promoted_from=promoted_from,
        prior_segment=prior_segment,
        thread_id=thread_id,
    )
    _mark_thread_promoted(store, records, slug=slug)
    mark_inbound_status_for_thread(thread_id, "promoted")
    rebuild_registry()

    return {
        "promoted": True,
        "slug": slug,
        "promoted_from": promoted_from,
        "prior_segment": prior_segment,
    }


def _promoted_from_label(records: list[RoutingRecord]) -> str:
    for rec in records:
        inbound_type = inbound_type_for_record(rec)
        if inbound_type:
            return f"inbound/{inbound_type}"
    return "inbound/unknown"


def _append_promotion_log(
    *,
    slug: str,
    promoted_from: str,
    prior_segment: str,
    thread_id: str,
) -> None:
    when = datetime.now(timezone.utc).date().isoformat()
    section = format_append_section(
        f"{when} — {slug}: {promoted_from} → connection",
        f"**Prior segment:** {prior_segment}\n",
        trigger="thread_watcher",
        why=f"two-way exchange (thread `{thread_id}`)",
    )
    write_wiki_page(
        promotion_log_path(),
        "CRM Promotion Log",
        section,
        mode=APPEND,
        section="crm",
        sync=False,
    )


def _mark_thread_promoted(
    store: RoutingStore,
    records: list[RoutingRecord],
    *,
    slug: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for rec in records:
        rec.extracted["crm_promoted_to"] = "connection"
        rec.extracted["crm_promoted_at"] = now
        rec.extracted["crm_contact_slug"] = slug
        store.write(rec)


def _mark_thread_engaged(
    store: RoutingStore,
    records: list[RoutingRecord],
    *,
    status: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for rec in records:
        rec.extracted["crm_engagement"] = status
        rec.extracted["crm_engaged_at"] = now
        store.write(rec)
