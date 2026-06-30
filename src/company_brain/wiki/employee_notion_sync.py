"""NotionSync wrapper for the employee wiki volume."""

from __future__ import annotations

from company_brain.notion.sync import NotionSync
from company_brain.wiki.employee_store import LocalEmployeeWikiStore, employee_wiki_store
from company_brain.wiki.store import WikiStore


class EmployeeNotionSync(NotionSync):
    """Mirror employee wiki Markdown pages to Notion using ``sync:`` routing."""

    def __init__(self, store: WikiStore | None = None, **kwargs):
        super().__init__(store=store or employee_wiki_store(), **kwargs)


def sync_employee_doc(
    rel_path: str,
    *,
    store: WikiStore | None = None,
    force: bool = False,
) -> str | None:
    """Sync one employee wiki page; returns Notion page id or None."""
    syncer = EmployeeNotionSync(store=store)
    return syncer.sync_doc(rel_path, force=force)
