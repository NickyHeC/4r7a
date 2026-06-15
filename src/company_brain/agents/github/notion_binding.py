"""Notion page discovery and binding for GitHub agents.

Implements the discover-or-create pattern: on first run, search Notion for
an existing page matching the agent's purpose. If found, persist the page ID.
If not, create a new page and persist that ID.
"""

from __future__ import annotations

import logging
import subprocess
import json
from pathlib import Path
from typing import Any

import yaml

from company_brain.config import CONFIG_DIR

logger = logging.getLogger(__name__)

GITHUB_PAGES_KEY = "github_agent_pages"


def _load_notion_yaml() -> dict[str, Any]:
    path = CONFIG_DIR / "notion.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _save_notion_yaml(data: dict[str, Any]) -> None:
    path = CONFIG_DIR / "notion.yaml"
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def get_bound_page_id(agent_key: str) -> str | None:
    """Return the stored Notion page ID for an agent, or None."""
    data = _load_notion_yaml()
    pages = data.get(GITHUB_PAGES_KEY, {})
    return pages.get(agent_key)


def bind_page_id(agent_key: str, page_id: str) -> None:
    """Persist a Notion page ID for an agent."""
    data = _load_notion_yaml()
    if GITHUB_PAGES_KEY not in data:
        data[GITHUB_PAGES_KEY] = {}
    data[GITHUB_PAGES_KEY][agent_key] = page_id
    _save_notion_yaml(data)
    logger.info("Bound agent '%s' to Notion page %s", agent_key, page_id)


def search_notion_page(title_query: str) -> str | None:
    """Search Notion for a page matching the title query. Returns page ID or None.

    Uses the Notion CLI (`ntn`) for search.
    """
    try:
        result = subprocess.run(
            ["ntn", "search", title_query, "--format", "json"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            logger.warning("ntn search failed: %s", result.stderr.strip())
            return None
        pages = json.loads(result.stdout) if result.stdout.strip() else []
        if pages:
            return pages[0].get("id")
    except FileNotFoundError:
        logger.error("Notion CLI (ntn) not found. Install: https://developers.notion.com/cli")
    return None


def create_notion_page(title: str, parent_id: str | None = None) -> str | None:
    """Create a new Notion page with the given title. Returns new page ID."""
    args = ["ntn", "page", "create", "--title", title, "--format", "json"]
    if parent_id:
        args.extend(["--parent", parent_id])
    try:
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("Failed to create Notion page: %s", result.stderr.strip())
            return None
        page = json.loads(result.stdout) if result.stdout.strip() else {}
        return page.get("id")
    except FileNotFoundError:
        logger.error("Notion CLI (ntn) not found.")
    return None


def ensure_notion_page(agent_key: str, search_terms: list[str], create_title: str) -> str | None:
    """Discover-or-create: return a bound page ID, searching and creating if needed."""
    page_id = get_bound_page_id(agent_key)
    if page_id:
        return page_id

    logger.info("First run for '%s' — searching Notion for existing page...", agent_key)
    for term in search_terms:
        page_id = search_notion_page(term)
        if page_id:
            logger.info("Found existing Notion page '%s' for '%s'", term, agent_key)
            bind_page_id(agent_key, page_id)
            return page_id

    logger.info("No existing page found. Creating '%s'...", create_title)
    root_id = _load_notion_yaml().get("root_page_id")
    page_id = create_notion_page(create_title, parent_id=root_id)
    if page_id:
        bind_page_id(agent_key, page_id)
    return page_id
