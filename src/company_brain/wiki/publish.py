"""Shared helper: write a wiki page MD-first, then mirror it to Notion.

Every agent that produces a page (operational or knowledge) calls
``write_wiki_page`` so the flow is uniform: write Markdown to the WikiStore
(source of truth), then sync to Notion. Existing frontmatter (notably the
``notion_page_id`` binding and ``created`` timestamp) is preserved across writes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Sequence

from company_brain.notion.sync import NotionSync
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc, WikiStore

logger = logging.getLogger(__name__)


def write_wiki_page(
    rel_path: str,
    title: str,
    body: str,
    *,
    section: str | None = None,
    type_: str = "page",
    sources: Sequence[str] | None = None,
    related: Sequence[str] | None = None,
    store: WikiStore | None = None,
    sync: bool = True,
) -> str | None:
    """Write a wiki page to the store and (optionally) sync it to Notion.

    Returns the Notion page id when synced, else None.
    """
    store = store or LocalWikiStore()
    p = PurePosixPath(rel_path)

    fm: dict = {}
    if store.exists(rel_path):
        fm = dict(store.read(rel_path).frontmatter or {})

    now = datetime.now(timezone.utc).isoformat()
    fm.setdefault("id", p.stem)
    fm["title"] = title
    fm["type"] = type_
    fm["section"] = section if section is not None else str(p.parent) if str(p.parent) != "." else ""
    fm.setdefault("created", now)
    fm["last_updated"] = now
    if related is not None:
        fm["related"] = list(related)
    else:
        fm.setdefault("related", [])
    if sources is not None:
        fm["sources"] = list(sources)
    else:
        fm.setdefault("sources", [])

    store.write(rel_path, MarkdownDoc(frontmatter=fm, body=body))
    logger.info("Wrote wiki page %s", rel_path)

    if not sync:
        return None
    try:
        return NotionSync(store=store).sync_doc(rel_path)
    except Exception:
        logger.exception("Notion sync failed for %s (MD source is still updated)", rel_path)
        return None


def read_wiki_page(rel_path: str, store: WikiStore | None = None) -> str:
    """Read a wiki page body from the store ('' if missing)."""
    store = store or LocalWikiStore()
    if not store.exists(rel_path):
        return ""
    return store.read(rel_path).body
