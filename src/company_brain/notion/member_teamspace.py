"""Discover-or-create Notion teamspace parents for employee wikis."""

from __future__ import annotations

import logging

from company_brain.config import AppConfig, load_config, save_notion_config
from company_brain.members_config import load_members_config
from company_brain.notion.client import NotionClient
from company_brain.notion.sync import _extract_page_id, _page_title

logger = logging.getLogger(__name__)


def member_teamspace_key(member_key: str) -> str:
    members = load_members_config()
    spec = members.get(member_key)
    if spec and spec.notion_teamspace:
        return spec.notion_teamspace
    return f"member_{member_key}"


def ensure_member_teamspace_parent(
    member_key: str,
    *,
    client: NotionClient | None = None,
    config: AppConfig | None = None,
    create: bool = True,
) -> str | None:
    """Return the Notion parent page id for a member's personal teamspace."""
    config = config or load_config()
    client = client or NotionClient()
    ts_key = member_teamspace_key(member_key)

    existing = (config.notion.teamspaces or {}).get(ts_key)
    if existing:
        return existing

    if not create:
        return None

    root = config.notion.root_page_id
    if not root:
        logger.warning("Cannot create member teamspace — notion.root_page_id unset")
        return None

    title = f"{member_key.replace('-', ' ').title()} — Employee Wiki"
    page_id = _discover_page_by_title(client, title)
    if not page_id:
        body = (
            f"Root for **{member_key}**'s employee wiki mirror. "
            "Pages with ``sync: private`` sync under this parent."
        )
        result = client.create_page(root, body, title=title)
        page_id = _extract_page_id(result.stdout, result.json_data)

    if not page_id:
        return None

    config.notion.teamspaces[ts_key] = page_id
    save_notion_config(config.notion)
    logger.info("Bound member teamspace %s -> Notion %s", ts_key, page_id)
    return page_id


def _discover_page_by_title(client: NotionClient, title: str) -> str | None:
    try:
        pages = client.search_all_pages()
    except Exception:
        return None
    needle = title.strip().lower()
    for page in pages:
        if _page_title(page).strip().lower() == needle:
            return page.get("id")
    return None
