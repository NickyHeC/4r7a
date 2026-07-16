"""Slack @wiki channel ACL — prefix-scoped wiki reads."""

from __future__ import annotations

from typing import Any

from company_brain.agents.operations.slack import channels_config
from company_brain.config import resolve_wiki_dir
from company_brain.wiki.retrieve import retrieve
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc

DENIED_SYNC = frozenset({"admin_only", "not_synced"})
DENIED_PREFIXES = ("admin/", "employee_wiki/")


def ask_wiki_allowed(channel_id: str) -> bool:
    if channels_config.is_connect_channel(channel_id):
        return False
    entry = channels_config.get_channel(channel_id) or {}
    if entry.get("ask_wiki_allowed") is False:
        return False
    return True


def wiki_prefixes(channel_id: str) -> list[str]:
    entry = channels_config.get_channel(channel_id) or {}
    raw = entry.get("wiki_prefixes") or []
    if isinstance(raw, list) and raw:
        return [str(p).strip() for p in raw if str(p).strip()]
    teamspace = str(entry.get("teamspace") or "").strip()
    if teamspace and teamspace != "company":
        return [f"{teamspace}/"]
    return ["company/"]


def path_allowed(rel_path: str, prefixes: list[str]) -> bool:
    from company_brain.wiki.retrieve import path_in_prefixes

    rel = rel_path.strip().strip("/")
    if not rel or any(rel.startswith(pfx) for pfx in DENIED_PREFIXES):
        return False
    return path_in_prefixes(rel, prefixes)


def _sync_allowed(doc: MarkdownDoc) -> bool:
    sync = str(doc.frontmatter.get("sync") or "").strip().lower()
    if sync in DENIED_SYNC:
        return False
    if sync.startswith("location:"):
        return True
    if sync in {"", "company", "private"}:
        return True
    return sync != "admin_only"


def search_wiki_snippets(
    query: str,
    *,
    channel_id: str,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Return allowed wiki snippets with Notion citation metadata."""
    prefixes = wiki_prefixes(channel_id)
    store = LocalWikiStore(root=resolve_wiki_dir())

    def allow(rel: str, doc: MarkdownDoc) -> bool:
        return path_allowed(rel, prefixes) and _sync_allowed(doc)

    hits = retrieve(
        query,
        store=store,
        allow=allow,
        deny_prefixes=DENIED_PREFIXES,
        limit=limit,
        snippet_chars=1200,
    )
    out: list[dict[str, Any]] = []
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
            }
        )
    return out


def _notion_url(page_id: str) -> str:
    if not page_id:
        return ""
    return f"https://www.notion.so/{page_id.replace('-', '')}"
