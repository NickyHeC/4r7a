"""Notion mirror routing from employee wiki ``sync:`` frontmatter labels."""

from __future__ import annotations

import logging
from typing import Any

from company_brain.config import AppConfig, load_config
from company_brain.members_config import load_members_config

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


def resolve_sync_parent(fm: dict[str, Any], config: AppConfig | None = None) -> str | None:
    """Resolve Notion parent page id from ``sync:`` frontmatter."""
    config = config or load_config()
    sync = (fm.get("sync") or "").strip()
    if not sync or sync == SYNC_NOT_SYNCED:
        return None

    teamspaces = config.notion.teamspaces or {}

    if sync == SYNC_ADMIN:
        return teamspaces.get("admin") or teamspaces.get("admin_only")

    if sync == SYNC_COMPANY:
        return teamspaces.get("company") or config.notion.root_page_id

    if sync.startswith("location:"):
        key = sync.split(":", 1)[1].strip()
        return teamspaces.get(key)

    if sync == SYNC_PRIVATE:
        member = (fm.get("member") or "").strip()
        if not member:
            logger.warning("sync:private page missing frontmatter member")
            return None
        members = load_members_config()
        spec = members.get(member)
        ts_key = (spec.notion_teamspace if spec else "") or f"member_{member}"
        parent = teamspaces.get(ts_key)
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
