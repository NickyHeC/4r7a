"""Apply triage classification to Gmail + routing store."""

from __future__ import annotations

import logging
from typing import Any

from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.classify import TriageResult
from company_brain.agents.operations.shared.labels import (
    apply_attention,
    apply_labels,
    archive,
    mark_read,
    mark_triaged,
)
from company_brain.agents.operations.shared.routing import RoutingStore, new_record

logger = logging.getLogger(__name__)


def apply_triage(
    message_id: str,
    result: TriageResult,
    *,
    mailbox: str,
    store: RoutingStore | None = None,
) -> dict[str, Any]:
    """Label, disposition, and persist routing record for one message."""
    store = store or RoutingStore()
    if store.exists(mailbox, message_id):
        return {"status": "skipped", "message_id": message_id, "reason": "already_triaged"}

    message = rest.get_message(message_id, mailbox=mailbox)
    thread_id = message.get("threadId", "")

    # Hidden domain labels (full Gmail label paths).
    for tag in result.domain_tags:
        rest.ensure_label(tag, visible=False, mailbox=mailbox)
    if result.domain_tags:
        apply_labels(message_id, add=result.domain_tags, mailbox=mailbox)

    # Visible attention queue (only 1–4 show in inbox list).
    if result.attention:
        apply_attention(message_id, result.attention, mailbox=mailbox)
    else:
        apply_attention(message_id, None, mailbox=mailbox)

    if result.mark_read:
        mark_read(message_id, mailbox=mailbox)

    if result.archive_now:
        archive(message_id, mailbox=mailbox)

    record = new_record(
        message_id=message_id,
        thread_id=thread_id,
        mailbox=mailbox,
        attention=result.attention,
        domain_tags=result.domain_tags,
        contact_type=result.contact_type,
        extracted=result.extracted,
        disposition={
            "mark_read": result.mark_read,
            "archive_now": result.archive_now,
        },
    )
    store.write(record)
    mark_triaged(message_id, mailbox=mailbox)

    return {
        "status": "triaged",
        "message_id": message_id,
        "attention": result.attention,
        "domain_tags": result.domain_tags,
    }


def collect_message_ids(*, mailbox: str, backfill_query: str | None = None) -> list[str]:
    """New messages via historyId delta, or backfill query when no cursor."""
    from company_brain.agents.operations.shared.gmail_state import GmailState

    state = GmailState()
    history_id = state.get_history_id(mailbox)

    if history_id:
        try:
            ids, latest = rest.history_message_ids(history_id, mailbox=mailbox)
            profile = rest.get_profile(mailbox)
            state.set_history_id(mailbox, latest or profile.get("historyId", history_id))
            return ids
        except rest.GmailAPIError as e:
            if e.status == 404:
                logger.warning("historyId expired — resetting cursor")
                state.set_history_id(mailbox, "")
            else:
                raise

    query = backfill_query or "in:inbox newer_than:7d"
    return list(rest.iter_messages(query, max_total=500, mailbox=mailbox))
