"""Slack @wiki channel ACL — prefix-scoped wiki reads."""

from __future__ import annotations

import re
from typing import Any

from company_brain.agents.operations.slack import channels_config
from company_brain.config import resolve_wiki_dir
from company_brain.wiki.store import CONTROL_FILES, LocalWikiStore, MarkdownDoc

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
    rel = rel_path.strip().strip("/")
    if not rel or any(rel.startswith(pfx) for pfx in DENIED_PREFIXES):
        return False
    for pfx in prefixes:
        base = pfx.rstrip("/")
        if rel == base or rel.startswith(base + "/"):
            return True
    return False


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
    terms = [t for t in re.split(r"\W+", (query or "").lower()) if len(t) >= 3]
    hits: list[tuple[int, dict[str, Any]]] = []

    for rel in store.list():
        name = rel.rsplit("/", 1)[-1]
        if name in CONTROL_FILES or not rel.endswith(".md"):
            continue
        if not path_allowed(rel, prefixes):
            continue
        try:
            doc = store.read(rel)
        except FileNotFoundError:
            continue
        if not _sync_allowed(doc):
            continue
        body = doc.body
        title = str(doc.frontmatter.get("title") or name)
        score = _score(terms, f"{title}\n{body}")
        if score <= 0 and terms:
            continue
        if not terms:
            score = 1
        notion_id = str(doc.frontmatter.get("notion_page_id") or "")
        hits.append(
            (
                score,
                {
                    "rel_path": rel,
                    "title": title,
                    "snippet": body[:1200],
                    "notion_page_id": notion_id,
                    "notion_url": _notion_url(notion_id),
                },
            )
        )

    hits.sort(key=lambda row: row[0], reverse=True)
    return [row[1] for row in hits[:limit]]


def _score(terms: list[str], text: str) -> int:
    lower = text.lower()
    return sum(lower.count(term) for term in terms)


def _notion_url(page_id: str) -> str:
    if not page_id:
        return ""
    return f"https://www.notion.so/{page_id.replace('-', '')}"
