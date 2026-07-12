"""Teamspace-scoped wiki snippet search for Notion ``@wiki`` fills."""

from __future__ import annotations

import re
from typing import Any

from company_brain.config import AppConfig
from company_brain.notion.sync_policy import COMPANY_FALLBACK_LOCATIONS
from company_brain.wiki.store import CONTROL_FILES, WikiStore

DENIED_PREFIXES = ("employee_wiki/",)
ADMIN_PREFIXES = ("admin/", "finance/", "legal/")
COMPANY_PREFIXES = (
    "company/",
    "engineering/",
    "product/",
    "growth/",
    "operations/",
    "crm/",
    "people/",
)


def teamspace_key_for_page(fm: dict[str, Any], config: AppConfig) -> str:
    """Resolve which Notion teamspace scopes reads for this page."""
    sync = str(fm.get("sync") or "").strip()
    if sync == "admin_only":
        return "admin"
    if sync == "company":
        return "company"
    if sync.startswith("location:"):
        key = sync.split(":", 1)[1].strip()
        if key in COMPANY_FALLBACK_LOCATIONS:
            parent = (config.notion.teamspaces or {}).get(key) or ""
            return key if parent.strip() else "company"
        return key or "company"
    section = str(fm.get("section") or "").strip("/")
    ts = config.notion.teamspace_for_section(section) if section else None
    if ts == "admin_only" or ts == "admin":
        return "admin"
    if ts:
        return ts
    # Path heuristic
    rel = str(fm.get("_rel_path") or "")
    if rel.startswith(ADMIN_PREFIXES) or section.startswith(("admin", "finance", "legal")):
        return "admin"
    return "company"


def prefixes_for_teamspace(teamspace: str) -> list[str]:
    if teamspace == "admin":
        return list(ADMIN_PREFIXES)
    if teamspace in COMPANY_FALLBACK_LOCATIONS:
        return [f"{teamspace}/", *COMPANY_PREFIXES]
    return list(COMPANY_PREFIXES)


def path_allowed(rel_path: str, prefixes: list[str]) -> bool:
    rel = rel_path.strip().strip("/")
    if not rel or any(rel.startswith(pfx) for pfx in DENIED_PREFIXES):
        return False
    for pfx in prefixes:
        base = pfx.rstrip("/")
        if rel == base or rel.startswith(base + "/"):
            return True
    return False


def search_scoped_snippets(
    query: str,
    *,
    store: WikiStore,
    prefixes: list[str],
    limit: int = 5,
    exclude: str | None = None,
) -> list[dict[str, Any]]:
    terms = [t for t in re.split(r"\W+", (query or "").lower()) if len(t) >= 3]
    hits: list[tuple[int, dict[str, Any]]] = []
    for rel in store.list():
        name = rel.rsplit("/", 1)[-1]
        if name in CONTROL_FILES or not rel.endswith(".md"):
            continue
        if exclude and rel == exclude:
            continue
        if not path_allowed(rel, prefixes):
            continue
        try:
            doc = store.read(rel)
        except FileNotFoundError:
            continue
        title = str(doc.frontmatter.get("title") or name)
        score = _score(terms, f"{title}\n{doc.body}")
        if score <= 0 and terms:
            continue
        hits.append(
            (
                score or 1,
                {
                    "rel_path": rel,
                    "title": title,
                    "snippet": doc.body[:800],
                },
            )
        )
    hits.sort(key=lambda x: (-x[0], x[1]["rel_path"]))
    return [h for _, h in hits[:limit]]


def build_fill_section(instruction: str, snippets: list[dict[str, Any]]) -> str:
    lines = [
        "## Wiki fill",
        "",
        f"**Request:** {instruction.strip() or '(fill)'}",
        "",
    ]
    if not snippets:
        lines.append("_No in-scope wiki sources found for this request._")
        lines.append("")
        return "\n".join(lines)
    lines.append("Sources used (teamspace-scoped):")
    lines.append("")
    for snip in snippets:
        lines.append(f"- [[{snip['rel_path'].removesuffix('.md')}]] — {snip['title']}")
    lines.append("")
    lines.append("### Compiled notes")
    lines.append("")
    for snip in snippets:
        excerpt = " ".join((snip.get("snippet") or "").split())[:400]
        lines.append(f"**{snip['title']}:** {excerpt}")
        lines.append("")
    return "\n".join(lines)


def _score(terms: list[str], text: str) -> int:
    low = text.lower()
    return sum(low.count(t) for t in terms)
