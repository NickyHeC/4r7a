"""Aggregate admin-attention action items for the Review pane.

Read-only triage surface — not a second write SoT. Deep-links to wiki edit
paths and fleet/state cues.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from company_brain.agents.gates import StateStore
from company_brain.wiki.store import LocalWikiStore, WikiStore

# Fixed pages that often hold open admin work.
_FIXED_PAGES: tuple[tuple[str, str, str], ...] = (
    ("weave_queue", "admin/weave-queue.md", "Weave queue"),
    ("stale_review", "operations/notion/review.md", "Stale Notion review"),
    ("conflict_log", "operations/notion/conflict-resolution.md", "Conflict resolutions"),
    ("ingest_queue", "operations/gmail/ingest-queue.md", "Gmail ingest queue"),
    ("manual_linear", "engineering/linear/manual-management.md", "Linear manual management"),
    ("install_progress", "admin/install-progress.md", "Install progress"),
)

# Directory prefixes for per-id review pages.
_PREFIX_QUEUES: tuple[tuple[str, str, str], ...] = (
    ("import_review", "admin/import-review/", "Import review"),
    ("mount_review", "admin/mount-review/", "Mount review"),
    ("knowledge_review", "admin/knowledge-review/", "Knowledge paste review"),
    ("notion_orphan", "admin/notion-orphan-review/", "Notion orphan review"),
    ("offboard", "hr/offboard-proposal/", "Offboard proposal"),
    ("maintain", "admin/maintain/", "Admin maintain"),
)


@dataclass
class ReviewItem:
    kind: str
    title: str
    source: str
    href: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _wiki_edit_href(rel: str) -> str:
    from urllib.parse import quote

    return f"/wiki/edit?path={quote(rel)}"


def _page_nonempty(store: WikiStore, rel: str) -> bool:
    if not store.exists(rel):
        return False
    try:
        doc = store.read(rel)
    except (OSError, FileNotFoundError):
        return False
    body = (doc.body or "").strip()
    # Skip stub / empty / "none" pages
    if not body:
        return False
    lower = body.lower()
    if lower in {"(empty)", "none", "n/a", "-"}:
        return False
    # Require some substance beyond a heading
    lines = [ln for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return len(lines) >= 1


def _collect_fixed(store: WikiStore) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for kind, rel, title in _FIXED_PAGES:
        if _page_nonempty(store, rel):
            items.append(
                ReviewItem(
                    kind=kind,
                    title=title,
                    source=rel,
                    href=_wiki_edit_href(rel),
                    detail="wiki",
                )
            )
    return items


def _collect_prefixes(store: WikiStore) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    listing = store.list()
    for kind, prefix, title in _PREFIX_QUEUES:
        for rel in listing:
            if not rel.startswith(prefix) or not rel.endswith(".md"):
                continue
            if not _page_nonempty(store, rel):
                continue
            slug = rel[len(prefix) :].removesuffix(".md")
            items.append(
                ReviewItem(
                    kind=kind,
                    title=f"{title} — {slug}",
                    source=rel,
                    href=_wiki_edit_href(rel),
                    detail="wiki",
                )
            )
    return items


def _collect_sync_conflicts(store: WikiStore, *, limit: int = 50) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for rel in store.list():
        if not rel.endswith(".md"):
            continue
        try:
            doc = store.read(rel)
        except (OSError, FileNotFoundError):
            continue
        fm = doc.frontmatter or {}
        if not fm.get("sync_conflict"):
            continue
        items.append(
            ReviewItem(
                kind="sync_conflict",
                title=str(fm.get("title") or rel),
                source=rel,
                href=_wiki_edit_href(rel),
                detail="frontmatter sync_conflict",
            )
        )
        if len(items) >= limit:
            break
    return items


def _collect_state_cues(*, store: StateStore | None = None) -> list[ReviewItem]:
    from company_brain.runtime.fleet_gate import redeploy_pending

    items: list[ReviewItem] = []
    state = store or StateStore()
    pending = redeploy_pending(store=state)
    if pending:
        detail_bits = []
        if pending.get("pr_url"):
            detail_bits.append(str(pending["pr_url"]))
        if pending.get("note"):
            detail_bits.append(str(pending["note"]))
        items.append(
            ReviewItem(
                kind="redeploy",
                title="Fleet redeploy cue",
                source="fleet:redeploy_requested",
                href="/status",
                detail=" · ".join(detail_bits) or "state.json",
            )
        )
    # Open install phases that are not ok
    for key in state.keys(prefix="install:"):
        payload = state.get(key)
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status") or "").lower()
        if status in {"failed", "error", "needs_attention", "blocked"}:
            items.append(
                ReviewItem(
                    kind="install",
                    title=f"Install: {key.removeprefix('install:')}",
                    source=key,
                    href=_wiki_edit_href("admin/install-progress.md"),
                    detail=status,
                )
            )
    # Latest upstream sync with a PR URL (informational actionable)
    for key in sorted(state.keys(prefix="admin_manager:upstream_sync:"), reverse=True)[:1]:
        payload = state.get(key)
        if isinstance(payload, dict) and payload.get("pr_url"):
            items.append(
                ReviewItem(
                    kind="upstream_sync",
                    title="Upstream sync draft PR",
                    source=key,
                    href=str(payload["pr_url"]),
                    detail="review + merge on GitHub",
                )
            )
    return items


def review_items(
    *, wiki: WikiStore | None = None, state: StateStore | None = None
) -> list[ReviewItem]:
    """Union of wiki review queues + state cues (sorted by kind, title)."""
    wiki = wiki or LocalWikiStore()
    items = (
        _collect_fixed(wiki)
        + _collect_prefixes(wiki)
        + _collect_sync_conflicts(wiki)
        + _collect_state_cues(store=state)
    )
    items.sort(key=lambda i: (i.kind, i.title.lower()))
    return items


def review_snapshot(
    *, wiki: WikiStore | None = None, state: StateStore | None = None
) -> dict[str, Any]:
    items = review_items(wiki=wiki, state=state)
    by_kind: dict[str, int] = {}
    for item in items:
        by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
    return {
        "count": len(items),
        "by_kind": by_kind,
        "items": [i.to_dict() for i in items],
    }
