"""Notion mirror routing from employee wiki ``sync:`` frontmatter labels."""

from __future__ import annotations

import logging
from typing import Any

from company_brain.config import AppConfig, load_config
from company_brain.members_config import load_members_config
from company_brain.notion.sync_policy import COMPANY_FALLBACK_LOCATIONS

logger = logging.getLogger(__name__)

SYNC_NOT_SYNCED = "not_synced"
SYNC_PRIVATE = "private"
SYNC_COMPANY = "company"
SYNC_ADMIN = "admin_only"


def should_skip_notion_mirror(fm: dict[str, Any], config: AppConfig | None = None) -> bool:
    """Return True when a page must not be mirrored to Notion."""
    config = config or load_config()
    sync = (fm.get("sync") or "").strip()

    if sync == SYNC_NOT_SYNCED:
        return True

    if sync:
        # Employee wiki pages use ``sync:`` — only ``not_synced`` skips mirror.
        return False

    section = fm.get("section") or ""
    return config.notion.teamspace_for_section(section) == "admin_only"


def resolve_teamspace_parent(key: str, config: AppConfig | None = None) -> str | None:
    """Resolve a teamspace key to a Notion parent page id.

    Default install uses admin + company. Optional engineering/product/growth
    splits use their own parents when set; otherwise those keys fall back to
    company (then root_page_id).
    """
    config = config or load_config()
    teamspaces = config.notion.teamspaces or {}
    key = (key or "").strip()
    if not key or key == "admin_only":
        return None
    parent = (teamspaces.get(key) or "").strip()
    if parent:
        return parent
    if key in COMPANY_FALLBACK_LOCATIONS:
        company = (teamspaces.get("company") or "").strip()
        return company or config.notion.root_page_id
    if key == "company":
        return config.notion.root_page_id
    return None


def resolve_sync_parent(fm: dict[str, Any], config: AppConfig | None = None) -> str | None:
    """Resolve Notion parent page id from ``sync:`` frontmatter."""
    config = config or load_config()
    sync = (fm.get("sync") or "").strip()
    if not sync or sync == SYNC_NOT_SYNCED:
        return None

    teamspaces = config.notion.teamspaces or {}

    if sync == SYNC_ADMIN:
        return (
            (teamspaces.get("admin") or "").strip()
            or (teamspaces.get("admin_only") or "").strip()
            or None
        )

    if sync == SYNC_COMPANY:
        return resolve_teamspace_parent("company", config)

    if sync.startswith("location:"):
        key = sync.split(":", 1)[1].strip()
        return resolve_teamspace_parent(key, config)

    if sync == SYNC_PRIVATE:
        member = (fm.get("member") or "").strip()
        if not member:
            logger.warning("sync:private page missing frontmatter member")
            return None
        members = load_members_config()
        spec = members.get(member)
        ts_key = (spec.notion_teamspace if spec else "") or f"member_{member}"
        parent = (teamspaces.get(ts_key) or "").strip()
        if parent:
            return parent
        logger.warning(
            "No Notion teamspace parent for member %s (key=%s); run employee_wiki_onboarding",
            member,
            ts_key,
        )
        return None

    logger.warning("Unknown sync label: %s", sync)
    return None
