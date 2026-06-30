"""Employee wiki store — per-member Markdown trees (sibling to company wiki)."""

from __future__ import annotations

from pathlib import Path

from company_brain.config import resolve_employee_wiki_dir
from company_brain.wiki.store import LocalWikiStore, WikiStore


class LocalEmployeeWikiStore(LocalWikiStore):
    """WikiStore rooted at ``employee_wiki/`` (or ``COMPANY_BRAIN_EMPLOYEE_WIKI_DIR``)."""

    def __init__(self, root: Path | None = None):
        super().__init__(root=root or resolve_employee_wiki_dir())


def employee_wiki_store(root: Path | None = None) -> WikiStore:
    return LocalEmployeeWikiStore(root=root)
