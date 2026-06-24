"""Receipt forwarding — copy receipt mail between company-domain inboxes.

Purpose: get receipts into the inbox Ramp watches so Ramp can auto-attach them.
Only copies between mailboxes on ``receipt_router.company_domain``; never sends
externally and never reconciles Ramp transactions (Ramp owns that).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.gates import is_handled, mark_handled
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import (
    connected_mailboxes,
    receipt_company_domain,
    receipt_destination_mailbox,
    receipt_forward_enabled,
)
from company_brain.agents.operations.shared.routing import RoutingStore

RECEIPTS_LABEL = "Receipts"
_GATE_PREFIX = "receipt_forward"


def forward_missing_receipts(
    *,
    since: datetime,
    missing_domains: set[str],
    store: RoutingStore | None = None,
) -> dict[str, Any]:
    """Copy receipt messages from sibling mailboxes into the Ramp destination inbox."""
    if not receipt_forward_enabled():
        return {"status": "disabled", "forwarded": 0}
    company_domain = receipt_company_domain()
    if not company_domain:
        return {"status": "no_company_domain", "forwarded": 0}
    if not missing_domains:
        return {"status": "nothing_missing", "forwarded": 0}

    destination = receipt_destination_mailbox()
    store = store or RoutingStore()
    forwarded = 0
    skipped = 0
    errors: list[str] = []

    for source_mb in _eligible_sources(destination, company_domain):
        for record in _receipt_candidates(store, source_mb, since, missing_domains):
            gate_key = f"{_GATE_PREFIX}:{source_mb}:{record.message_id}:{destination}"
            if is_handled(gate_key, "done"):
                skipped += 1
                continue
            try:
                rest.copy_message_to_mailbox(
                    record.message_id,
                    from_mailbox=source_mb,
                    to_mailbox=destination,
                    label_names=[RECEIPTS_LABEL],
                )
            except Exception as exc:
                errors.append(f"{source_mb}:{record.message_id}: {exc}")
                continue
            record.extracted["receipt_forwarded_to"] = destination
            record.extracted["receipt_forwarded_at"] = datetime.now(timezone.utc).isoformat()
            store.write(record)
            mark_handled(gate_key, "done")
            forwarded += 1

    return {
        "status": "ok",
        "forwarded": forwarded,
        "skipped": skipped,
        "errors": errors,
        "destination": destination,
    }


def _eligible_sources(destination: str, company_domain: str) -> list[str]:
    out: list[str] = []
    for mailbox in connected_mailboxes():
        if mailbox == destination:
            continue
        if not rest.mailbox_on_company_domain(mailbox, company_domain):
            continue
        out.append(mailbox)
    return out


def _receipt_candidates(
    store: RoutingStore,
    mailbox: str,
    since: datetime,
    missing_domains: set[str],
):
    for record in store.iter_mailbox(mailbox):
        if RECEIPTS_LABEL not in record.domain_tags:
            continue
        if _parse_triaged(record.triaged_at) < since:
            continue
        domain = _domain_from(record.extracted.get("from", ""))
        if domain not in missing_domains:
            continue
        if record.extracted.get("receipt_forwarded_to"):
            continue
        yield record


def _parse_triaged(raw: str) -> datetime:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _domain_from(from_hdr: str) -> str:
    if "@" not in from_hdr:
        return from_hdr.lower()
    return from_hdr.split("@")[-1].split(">")[0].strip().lower()
