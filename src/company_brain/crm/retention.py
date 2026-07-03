"""CRM inbound retention helpers for inbox_sweep."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from company_brain.agents.operations.shared.routing import RoutingRecord
from company_brain.crm.config import inbound_retention_days
from company_brain.crm.inbound import INBOUND_TAGS

# Legacy specialist keys before unified inbound_crm.
INBOUND_HANDLED_KEYS = frozenset(
    {
        "inbound_crm",
        "partnership_digest",
        "growth_inbound",
        "recruiting_inbound",
    }
)


def crm_inbound_tags(record: RoutingRecord) -> bool:
    return bool(INBOUND_TAGS.intersection(record.domain_tags))


def inbound_handled(record: RoutingRecord) -> bool:
    return bool(INBOUND_HANDLED_KEYS.intersection(record.handled))


def triaged_at_older_than(record: RoutingRecord, *, days: int | None = None) -> bool:
    """True when ``triaged_at`` is at least ``days`` calendar days ago."""
    raw = record.triaged_at
    if not raw:
        return False
    try:
        triaged = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if triaged.tzinfo is None:
            triaged = triaged.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    age = days if days is not None else inbound_retention_days()
    cutoff = datetime.now(timezone.utc) - timedelta(days=age)
    return triaged <= cutoff


def crm_inbound_archive_due(record: RoutingRecord) -> bool:
    """Whether a CRM cold-inbound message should leave the inbox (time-based retention)."""
    if not crm_inbound_tags(record):
        return False
    if not inbound_handled(record):
        return False
    return triaged_at_older_than(record)
