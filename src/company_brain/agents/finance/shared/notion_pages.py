"""Finance page helper, backed by the Markdown wiki store.

Historically this discovered-or-created Notion pages directly. Under the new
data flow the Markdown wiki is the source of truth and Notion is a synced
mirror, so these helpers now read/write wiki Markdown pages (via the shared
``write_wiki_page``/``read_wiki_page`` helpers) and let ``NotionSync`` handle
the Notion mirroring. Page "handles" are wiki rel_paths.
"""

from __future__ import annotations

import logging

from company_brain.config import resolve_wiki_dir
from company_brain.wiki.publish import read_wiki_page, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

logger = logging.getLogger(__name__)

# Stable finance key -> wiki rel_path.
_KEY_PATHS = {
    "monthly_expense_reports": "finance/expense-reports.md",
    "quarterly_metric": "finance/quarterly-metric.md",
    "budget_summary": "finance/budget-summary.md",
    "company_timeline": "finance/company-timeline.md",
    "company_subscriptions": "finance/company-subscriptions.md",
    "manual_accounting": "finance/manual-accounting.md",
}


def wiki_path(key: str) -> str:
    """Map a finance key (including dynamic ``monthly_expense_<YYYY-MM>``) to a path."""
    if key.startswith("monthly_expense_") and key != "monthly_expense_reports":
        month = key[len("monthly_expense_"):]
        return f"finance/expense-reports/{month}.md"
    return _KEY_PATHS.get(key, f"finance/{key.replace('_', '-')}.md")


def ensure_page(key: str, search_terms: list[str], create_title: str,
                parent_key: str | None = None) -> str:
    """Return the wiki rel_path for a finance page (handle for read/write)."""
    return wiki_path(key)


def get_bound_id(key: str) -> str | None:
    """Return the page handle (rel_path) if that wiki page exists, else None."""
    path = wiki_path(key)
    return path if LocalWikiStore().exists(path) else None


def update_page_body(rel_path: str, body: str) -> bool:
    """Overwrite a wiki page body (MD source of truth), then sync to Notion."""
    write_wiki_page(rel_path, _title_for(rel_path, body), body, section="finance", type_="report")
    return True


def prepend_page_body(rel_path: str, body: str) -> bool:
    """Append a new section to a wiki page (newest on top), then sync to Notion."""
    from company_brain.wiki.publish import APPEND

    write_wiki_page(
        rel_path, _title_for(rel_path, body), body,
        mode=APPEND, section="finance", type_="report",
    )
    return True


def read_page(rel_path: str) -> str:
    """Read a wiki page body from the store ('' if missing)."""
    return read_wiki_page(rel_path)


def page_url(rel_path: str) -> str:
    """Notion URL for a synced page (from frontmatter binding), else the wiki path."""
    store = LocalWikiStore()
    if store.exists(rel_path):
        pid = (store.read(rel_path).frontmatter or {}).get("notion_page_id")
        if pid:
            return f"https://www.notion.so/{str(pid).replace('-', '')}"
    return str(resolve_wiki_dir() / rel_path)


def _title_for(rel_path: str, body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    stem = rel_path.rsplit("/", 1)[-1].removesuffix(".md")
    return stem.replace("-", " ").title()
