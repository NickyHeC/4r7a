"""Shared wiki page relocation — move MD to a new path, leave a stub at the old one.

Used by ``@wiki move`` (``wiki_directive``) and ``page_relocate_to`` (``page_system``).
MD first; optional NotionSync push to the destination path.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from company_brain.agents.operations.notion import platform_config
from company_brain.config import AppConfig
from company_brain.notion.sync import NotionSync
from company_brain.notion.sync_policy import body_hash
from company_brain.wiki.store import MarkdownDoc, WikiStore

logger = logging.getLogger(__name__)


def relocate_page(
    *,
    store: WikiStore,
    config: AppConfig,
    from_path: str,
    to_path: str,
    fm: dict[str, Any],
    body: str,
    title: str,
    when: datetime,
    sync: bool = True,
) -> None:
    """Move page content to ``to_path`` and leave a stub at ``from_path``.

    Transfers ``notion_page_id`` to the destination when present. The stub at
    ``from_path`` is MD-only (redirect wikilink) until ``stub_ttl_days`` cleanup.
    """
    ttl = platform_config.stub_ttl_days()
    expires = (when + timedelta(days=ttl)).isoformat()
    new_fm = dict(fm)
    new_fm["title"] = title
    section = str(PurePosixPath(to_path).parent)
    new_fm["section"] = "" if section == "." else section
    new_fm["last_updated"] = when.isoformat()
    new_fm["synced_hash"] = body_hash(body)
    new_fm.pop("stub", None)
    new_fm.pop("stub_target", None)
    new_fm.pop("stub_expires_at", None)
    new_fm.pop("page_relocate_to", None)
    new_fm.pop("misplaced_to", None)
    new_fm.pop("misplaced", None)
    new_fm["relocated_from"] = from_path

    store.write(to_path, MarkdownDoc(frontmatter=new_fm, body=body))

    stub_title = f"Moved — {title}"
    stub_body = (
        f"# {stub_title}\n\n"
        f"This page moved to [[{to_path.removesuffix('.md')}]].\n\n"
        f"Stub expires {expires[:10]}.\n"
    )
    stub_section = str(PurePosixPath(from_path).parent)
    stub_fm = {
        "title": stub_title,
        "type": "stub",
        "stub": True,
        "stub_target": to_path,
        "stub_expires_at": expires,
        "section": "" if stub_section == "." else stub_section,
        "created": when.isoformat(),
        "last_updated": when.isoformat(),
    }
    if fm.get("notion_page_id"):
        new_doc = store.read(to_path)
        nfm = dict(new_doc.frontmatter)
        nfm["notion_page_id"] = fm["notion_page_id"]
        store.write(to_path, MarkdownDoc(frontmatter=nfm, body=new_doc.body))

    store.write(from_path, MarkdownDoc(frontmatter=stub_fm, body=stub_body))

    if sync:
        try:
            NotionSync(store=store, config=config).sync_doc(to_path, force=True)
        except Exception:
            logger.exception("Notion sync failed after move to %s", to_path)
