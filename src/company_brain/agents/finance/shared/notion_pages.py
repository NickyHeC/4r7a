"""Notion page/database discovery and binding for finance agents.

Implements the project-wide discover-or-create pattern (see the engineering
GitHub ``notion_binding`` helper). On first use an agent searches the workspace
for an existing page/database that fits its purpose; if found it binds and
persists the ID, otherwise it creates one. Bindings are stored under the
``finance_pages`` block of ``config/notion.yaml``.

All Notion access goes through the Notion CLI (``ntn``).
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

import yaml

from company_brain.config import CONFIG_DIR

logger = logging.getLogger(__name__)

FINANCE_PAGES_KEY = "finance_pages"


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


def get_bound_id(key: str) -> str | None:
    """Return the stored Notion page/database ID for a finance binding key."""
    return _load_notion_yaml().get(FINANCE_PAGES_KEY, {}).get(key)


def bind_id(key: str, page_id: str) -> None:
    """Persist a Notion page/database ID under the finance bindings block."""
    data = _load_notion_yaml()
    data.setdefault(FINANCE_PAGES_KEY, {})
    data[FINANCE_PAGES_KEY][key] = page_id
    _save_notion_yaml(data)
    logger.info("Bound finance key '%s' to Notion id %s", key, page_id)


def search_page(title_query: str) -> str | None:
    """Search Notion for a page/database matching a title query; return id or None."""
    try:
        result = subprocess.run(
            ["ntn", "search", title_query, "--format", "json"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            logger.warning("ntn search failed: %s", result.stderr.strip())
            return None
        items = json.loads(result.stdout) if result.stdout.strip() else []
        if items:
            return items[0].get("id")
    except FileNotFoundError:
        logger.error("Notion CLI (ntn) not found. Install: https://developers.notion.com/cli")
    return None


def create_page(title: str, parent_id: str | None = None) -> str | None:
    """Create a Notion page with the given title; return its id."""
    args = ["ntn", "page", "create", "--title", title, "--format", "json"]
    if parent_id:
        args.extend(["--parent", parent_id])
    try:
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("Failed to create Notion page '%s': %s", title, result.stderr.strip())
            return None
        page = json.loads(result.stdout) if result.stdout.strip() else {}
        return page.get("id")
    except FileNotFoundError:
        logger.error("Notion CLI (ntn) not found.")
    return None


def ensure_page(key: str, search_terms: list[str], create_title: str,
                parent_key: str | None = None) -> str | None:
    """Discover-or-create: return a bound id, searching/creating if needed.

    If ``parent_key`` is given, a newly created page is nested under the page
    bound to that key (e.g. a monthly report under ``Monthly Expense Reports``).
    """
    page_id = get_bound_id(key)
    if page_id:
        return page_id

    logger.info("First use of finance page '%s' — searching Notion...", key)
    for term in search_terms:
        page_id = search_page(term)
        if page_id:
            logger.info("Found existing Notion page '%s' for '%s'", term, key)
            bind_id(key, page_id)
            return page_id

    parent_id = get_bound_id(parent_key) if parent_key else _load_notion_yaml().get("root_page_id")
    logger.info("No existing page found for '%s'. Creating '%s'...", key, create_title)
    page_id = create_page(create_title, parent_id=parent_id)
    if page_id:
        bind_id(key, page_id)
    return page_id


def update_page_body(page_id: str, body: str) -> bool:
    """Overwrite a Notion page body."""
    return _run_ntn(["page", "update", page_id, "--body", body])


def prepend_page_body(page_id: str, body: str) -> bool:
    """Prepend content to a Notion page body (newest on top)."""
    return _run_ntn(["page", "prepend", page_id, "--body", body])


def read_page(page_id: str) -> str:
    """Read a Notion page as markdown (empty string on failure)."""
    try:
        result = subprocess.run(
            ["ntn", "page", "read", page_id, "--format", "markdown"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout
    except FileNotFoundError:
        logger.error("Notion CLI (ntn) not found.")
    return ""


def page_url(page_id: str) -> str:
    """Best-effort Notion URL for a page id."""
    return f"https://www.notion.so/{page_id.replace('-', '')}"


def _run_ntn(args: list[str]) -> bool:
    try:
        result = subprocess.run(["ntn", *args], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("ntn %s failed: %s", args[0], result.stderr.strip())
            return False
        return True
    except FileNotFoundError:
        logger.error("Notion CLI (ntn) not found.")
        return False
