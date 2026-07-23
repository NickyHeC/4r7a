"""@wiki planner fan-out — parallel wiki + CRM + practices (max 3; fail closed)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from company_brain.agents.operations.slack.wiki_acl import path_allowed, wiki_prefixes
from company_brain.config import resolve_wiki_dir
from company_brain.wiki.project_registry import prefixes_for_channel
from company_brain.wiki.retrieve import retrieve
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc

MAX_FETCHES = 3


def effective_wiki_prefixes(channel_id: str) -> list[str]:
    project_prefixes = prefixes_for_channel(channel_id)
    if project_prefixes:
        return project_prefixes
    return wiki_prefixes(channel_id)


def plan_and_fetch(
    query: str,
    *,
    channel_id: str,
    limit_per_source: int = 4,
) -> list[dict[str, Any]]:
    """Fan out up to 3 sources; on any failure fall back to wiki-only retrieve."""
    fetches: list[tuple[str, Callable[[], list[dict[str, Any]]]]] = [
        (
            "wiki",
            lambda: _fetch_wiki(query, channel_id=channel_id, limit=limit_per_source),
        ),
        (
            "crm",
            lambda: _fetch_crm(query, channel_id=channel_id, limit=limit_per_source),
        ),
        (
            "practices",
            lambda: _fetch_practices(query, channel_id=channel_id, limit=limit_per_source),
        ),
    ]
    fetches = fetches[:MAX_FETCHES]
    results: list[dict[str, Any]] = []
    errors = 0
    with ThreadPoolExecutor(max_workers=MAX_FETCHES) as pool:
        futures = {pool.submit(fn): name for name, fn in fetches}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                hits = fut.result()
                for hit in hits:
                    hit = dict(hit)
                    hit["source"] = name
                    results.append(hit)
            except Exception:
                errors += 1
    if errors and not results:
        # Fail closed: wiki-only single path
        return _fetch_wiki(query, channel_id=channel_id, limit=limit_per_source)
    if errors:
        # Partial failure — keep successful sources; ensure wiki present
        if not any(r.get("source") == "wiki" for r in results):
            try:
                results.extend(_fetch_wiki(query, channel_id=channel_id, limit=limit_per_source))
            except Exception:
                pass
    # Dedup by rel_path, prefer higher score
    by_path: dict[str, dict[str, Any]] = {}
    for hit in results:
        rel = str(hit.get("rel_path") or "")
        if not rel:
            continue
        prev = by_path.get(rel)
        if prev is None or float(hit.get("score") or 0) > float(prev.get("score") or 0):
            by_path[rel] = hit
    ranked = sorted(by_path.values(), key=lambda h: float(h.get("score") or 0), reverse=True)
    return ranked[: max(limit_per_source * 2, 6)]


def _fetch_wiki(query: str, *, channel_id: str, limit: int) -> list[dict[str, Any]]:
    # Temporarily override prefixes via project registry by patching search
    prefixes = effective_wiki_prefixes(channel_id)
    store = LocalWikiStore(root=resolve_wiki_dir())

    def allow(rel: str, doc: MarkdownDoc) -> bool:
        from company_brain.agents.operations.slack.wiki_acl import _sync_allowed

        return path_allowed(rel, prefixes) and _sync_allowed(doc)

    hits = retrieve(
        query,
        store=store,
        allow=allow,
        deny_prefixes=("admin/", "employee_wiki/"),
        limit=limit,
        snippet_chars=1200,
    )
    out = []
    for hit in hits:
        notion_id = str(hit.get("notion_page_id") or "")
        out.append(
            {
                "rel_path": hit["rel_path"],
                "title": hit["title"],
                "snippet": hit["snippet"],
                "score": hit.get("score"),
                "notion_page_id": notion_id,
                "notion_url": _notion_url(notion_id),
                "source": "wiki",
            }
        )
    return out


def _fetch_crm(query: str, *, channel_id: str, limit: int) -> list[dict[str, Any]]:
    prefixes = effective_wiki_prefixes(channel_id)
    # Only when channel ACL already includes crm/ or company-wide
    if not any(p.startswith("crm") or p in {"company/", ""} for p in prefixes):
        # Allow CRM when company-scoped channels
        entry_prefixes = wiki_prefixes(channel_id)
        if not any(p.startswith("crm") or p.startswith("company") for p in entry_prefixes):
            return []
    store = LocalWikiStore(root=resolve_wiki_dir())

    def allow(rel: str, doc: MarkdownDoc) -> bool:
        return rel.startswith("crm/") and not str(doc.frontmatter.get("sync") or "").startswith(
            "admin_only"
        )

    hits = retrieve(query, store=store, allow=allow, limit=limit, snippet_chars=800)
    return [
        {
            "rel_path": h["rel_path"],
            "title": h["title"],
            "snippet": h["snippet"],
            "score": h.get("score"),
            "notion_page_id": str(h.get("notion_page_id") or ""),
            "notion_url": _notion_url(str(h.get("notion_page_id") or "")),
            "source": "crm",
        }
        for h in hits
    ]


def _fetch_practices(query: str, *, channel_id: str, limit: int) -> list[dict[str, Any]]:
    prefixes = effective_wiki_prefixes(channel_id)
    practice_roots = []
    for p in prefixes:
        root = p.strip("/")
        if not root:
            continue
        # department/practices or engineering/practices
        practice_roots.append(f"{root}/practices/")
        if "/" not in root:
            practice_roots.append(f"{root}/practices/")
    # Always try engineering practices when eng prefixes present
    if any("engineering" in p for p in prefixes):
        practice_roots.append("engineering/practices/")
    if not practice_roots:
        return []
    store = LocalWikiStore(root=resolve_wiki_dir())

    def allow(rel: str, doc: MarkdownDoc) -> bool:
        return "practices" in rel and any(rel.startswith(r) for r in practice_roots)

    hits = retrieve(query, store=store, allow=allow, limit=limit, snippet_chars=800)
    return [
        {
            "rel_path": h["rel_path"],
            "title": h["title"],
            "snippet": h["snippet"],
            "score": h.get("score"),
            "notion_page_id": str(h.get("notion_page_id") or ""),
            "notion_url": _notion_url(str(h.get("notion_page_id") or "")),
            "source": "practices",
        }
        for h in hits
    ]


def _notion_url(page_id: str) -> str:
    if not page_id:
        return ""
    return f"https://www.notion.so/{page_id.replace('-', '')}"


__all__ = ["MAX_FETCHES", "plan_and_fetch", "effective_wiki_prefixes"]
