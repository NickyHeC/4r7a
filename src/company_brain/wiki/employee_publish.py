"""Write employee wiki pages MD-first (Notion sync deferred to Phase C)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from company_brain.wiki.employee_store import employee_wiki_store
from company_brain.wiki.store import MarkdownDoc, WikiStore

logger = logging.getLogger(__name__)

UPDATE = "update"
APPEND = "append"

DEFAULT_SYNC = "private"
VALID_SYNC = frozenset({"private", "company", "admin_only", "not_synced"})


def write_employee_wiki_page(
    rel_path: str,
    title: str,
    body: str,
    *,
    member: str,
    mode: str = UPDATE,
    sync: str = DEFAULT_SYNC,
    artifact_refs: Sequence[str] | None = None,
    company_links: Sequence[str] | None = None,
    sources: Sequence[str] | None = None,
    submit_to_company: str = "none",
    duplicate_of: str | None = None,
    extra_frontmatter: Mapping[str, Any] | None = None,
    store: WikiStore | None = None,
    mirror_notion: bool = True,
) -> str | None:
    """Write an employee wiki page with standard frontmatter defaults.

    Mirrors to Notion when ``mirror_notion`` is True and ``sync`` is not ``not_synced``.
    Returns the Notion page id when synced, else None.
    """
    if sync not in VALID_SYNC and not sync.startswith("location:"):
        raise ValueError(f"invalid sync label: {sync}")

    store = store or employee_wiki_store()
    p = PurePosixPath(rel_path)

    fm: dict[str, Any] = {}
    if store.exists(rel_path):
        fm = dict(store.read(rel_path).frontmatter or {})

    if mode == APPEND:
        body = _prepend_section(store, rel_path, title, body)

    now = datetime.now(timezone.utc).isoformat()
    if extra_frontmatter:
        fm.update(extra_frontmatter)
    fm.setdefault("id", p.stem)
    fm["title"] = title
    fm["member"] = member
    fm["sync"] = sync
    fm.setdefault("submit_to_company", submit_to_company)
    fm.setdefault("created", now)
    fm["last_updated"] = now
    if artifact_refs is not None:
        fm["artifact_refs"] = list(artifact_refs)
    else:
        fm.setdefault("artifact_refs", [])
    if company_links is not None:
        fm["company_links"] = list(company_links)
    else:
        fm.setdefault("company_links", [])
    if sources is not None:
        fm["sources"] = list(sources)
    else:
        fm.setdefault("sources", [])
    if duplicate_of:
        fm["duplicate_of"] = duplicate_of

    store.write(rel_path, MarkdownDoc(frontmatter=fm, body=body))
    logger.info("Wrote employee wiki page %s (mode=%s sync=%s)", rel_path, mode, sync)

    if not mirror_notion or sync == "not_synced":
        return None
    try:
        from company_brain.wiki.employee_notion_sync import sync_employee_doc

        return sync_employee_doc(rel_path, store=store)
    except Exception:
        logger.exception("Notion sync failed for employee page %s (MD updated)", rel_path)
        return None


def read_employee_wiki_page(rel_path: str, store: WikiStore | None = None) -> str:
    store = store or employee_wiki_store()
    if not store.exists(rel_path):
        return ""
    return store.read(rel_path).body


def _prepend_section(store: WikiStore, rel_path: str, title: str, section: str) -> str:
    prior = ""
    if store.exists(rel_path):
        existing = store.read(rel_path).body
        if existing.lstrip().startswith("# "):
            after = existing.split("\n", 1)
            prior = after[1].lstrip("\n") if len(after) > 1 else ""
        else:
            prior = existing
    parts = [f"# {title}", "", section.strip()]
    if prior.strip():
        parts += ["", prior.strip()]
    return "\n".join(parts).rstrip() + "\n"
