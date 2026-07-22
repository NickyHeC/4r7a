"""Wiki search / read / edit for the admin console (full MD tree)."""

from __future__ import annotations

from typing import Any

from company_brain.admin_console import audit
from company_brain.wiki.publish import UPDATE, read_wiki_page, write_wiki_page
from company_brain.wiki.retrieve import retrieve
from company_brain.wiki.store import LocalWikiStore


def search_wiki(query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    store = LocalWikiStore()
    return retrieve(query, store=store, limit=limit)


def get_page(rel_path: str) -> dict[str, Any]:
    store = LocalWikiStore()
    rel = rel_path.strip().lstrip("/")
    try:
        doc = store.read(rel)
    except FileNotFoundError as exc:
        raise FileNotFoundError(rel) from exc
    title = str(doc.frontmatter.get("title") or rel)
    conflict = bool(doc.frontmatter.get("sync_conflict"))
    return {
        "rel_path": rel,
        "title": title,
        "body": doc.body,
        "frontmatter": dict(doc.frontmatter or {}),
        "sync_conflict": conflict,
        "human_override_note": doc.frontmatter.get("human_override_note") or "",
    }


def save_page(rel_path: str, title: str, body: str, *, sync: bool = True) -> dict[str, Any]:
    rel = rel_path.strip().lstrip("/")
    if not rel.endswith(".md"):
        raise ValueError("rel_path must end with .md")
    from company_brain.agents.admin.knowledge_paste import is_untrusted_wiki_path
    from company_brain.wiki.import_scan import ImportLimits, scan_import_files

    if is_untrusted_wiki_path(rel):
        raise ValueError(
            f"Path `{rel}` must use `company-brain admin knowledge paste` "
            "(quarantine + scan); console save blocked for untrusted namespaces."
        )
    scan = scan_import_files(
        {rel: body},
        limits=ImportLimits(max_files=1, max_file_bytes=1_048_576),
    )
    if not scan.ok:
        reasons = "; ".join(f.reason for f in scan.blocked())
        raise ValueError(f"Blocked by import scan: {reasons}")
    section = rel.split("/", 1)[0] if "/" in rel else "admin"
    audit.append_event("wiki_edit", rel_path=rel, title=title)
    write_wiki_page(
        rel,
        title.strip() or rel,
        body,
        mode=UPDATE,
        section=section,
        type_="page",
        sync=sync,
    )
    return {"status": "ok", "rel_path": rel, "title": title}


def read_page_text(rel_path: str) -> str:
    return read_wiki_page(rel_path.strip().lstrip("/"))
