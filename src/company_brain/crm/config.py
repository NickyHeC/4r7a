"""Typed helpers for ``config/operations.yaml`` → ``crm`` section."""

from __future__ import annotations

from typing import Any

from company_brain.agents.operations.shared.config import load_operations_config

SEGMENTS = frozenset({"customer", "investor", "connection"})
INBOUND_TYPES = frozenset(
    {
        "press-podcast",
        "event-invitation",
        "partnership",
        "founder-networking",
        "investor-interest",
        "candidate",
        "unmatched",
    }
)


def crm_cfg() -> dict[str, Any]:
    return load_operations_config().get("crm") or {}


def contact_dir() -> str:
    return crm_cfg().get("contact_dir", "crm/contact")


def inbound_dir() -> str:
    return crm_cfg().get("inbound_dir", "crm/inbound")


def registry_path() -> str:
    return crm_cfg().get("registry_path", "crm/_registry.json")


def promotion_log_path() -> str:
    return crm_cfg().get("promotion_log", "crm/promotion-log.md")


def customer_index_path() -> str:
    return crm_cfg().get("customer_index", "crm/customer/_index.md")


def investor_index_path() -> str:
    return crm_cfg().get("investor_index", "crm/investor/_index.md")


def inbound_retention_days() -> int:
    return int(crm_cfg().get("inbound_retention_days", 7))


def slack_score_threshold() -> int:
    return int(crm_cfg().get("slack_score_threshold", 6))


def growth_channel() -> str:
    return crm_cfg().get("growth_channel", "#growth")


def reputable_domains() -> set[str]:
    return {str(d).lower() for d in (crm_cfg().get("reputable_domains") or [])}


def inbound_type_dir(inbound_type: str) -> str:
    if inbound_type not in INBOUND_TYPES:
        raise ValueError(f"unknown inbound type: {inbound_type}")
    return f"{inbound_dir().rstrip('/')}/{inbound_type}"


def contact_rel_path(slug: str) -> str:
    return f"{contact_dir().rstrip('/')}/{slug}.md"


def default_connection_employee() -> str:
    return str(crm_cfg().get("default_connection_employee") or "").strip()
