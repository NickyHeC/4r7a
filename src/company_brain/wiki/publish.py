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
from typing import Any, Sequence

from company_brain.notion.sync import NotionSync
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc, WikiStore

logger = logging.getLogger(__name__)


UPDATE = "update"
APPEND = "append"


def write_wiki_page(
    rel_path: str,
    title: str,
    body: str,
    *,
    mode: str = UPDATE,
    section: str | None = None,
    type_: str = "page",
    sources: Sequence[str] | None = None,
    related: Sequence[str] | None = None,
    store: WikiStore | None = None,
    sync: bool = True,
    sync_label: str | None = None,
    extra_frontmatter: dict[str, Any] | None = None,
) -> str | None:
    """Write a wiki page to the store and (optionally) sync it to Notion.

    ``mode``:
    - ``"update"`` (default): ``body`` replaces the whole page body (overwrite).
      Use for pages that show a current snapshot (open PRs, branch status).
    - ``"append"``: ``body`` is a NEW SECTION prepended under the page heading,
      above prior sections, so the newest run appears on top. Use for running
      logs (weekly updates, quarterly metrics, monthly reports, asset snapshots).

    Returns the Notion page id when synced, else None.
    """
    store = store or LocalWikiStore()
    p = PurePosixPath(rel_path)

    fm: dict = {}
    if store.exists(rel_path):
        fm = dict(store.read(rel_path).frontmatter or {})

    if mode == APPEND:
        body = _prepend_section(store, rel_path, title, body)

    now = datetime.now(timezone.utc).isoformat()
    fm.setdefault("id", p.stem)
    fm["title"] = title
    fm["type"] = type_
    if section is not None:
        fm["section"] = section
    else:
        parent = str(p.parent)
        fm["section"] = parent if parent != "." else ""
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
    if sync_label is not None:
        fm["sync"] = sync_label
    if extra_frontmatter:
        fm.update(extra_frontmatter)

    store.write(rel_path, MarkdownDoc(frontmatter=fm, body=body))
    logger.info("Wrote wiki page %s (mode=%s)", rel_path, mode)

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


def _prepend_section(store: WikiStore, rel_path: str, title: str, section: str) -> str:
    """Assemble an append-mode body: title heading, newest section, prior sections."""
    prior = ""
    if store.exists(rel_path):
        existing = store.read(rel_path).body
        # Drop a leading "# Title" heading so we keep a single page heading.
        if existing.lstrip().startswith("# "):
            after = existing.split("\n", 1)
            prior = after[1].lstrip("\n") if len(after) > 1 else ""
        else:
            prior = existing
    parts = [f"# {title}", "", section.strip()]
    if prior.strip():
        parts += ["", prior.strip()]
    return "\n".join(parts).rstrip() + "\n"
