"""Notion orphan discovery — weekly crawl of teamspace roots for unbound pages.

Flags Notion pages under configured teamspace parents that have no MD
``notion_page_id`` binding. Writes ``admin/notion-orphan-review/{id}.md`` for
Adopt / Ignore / Archive. Never auto-adopts.

SDK: Neither (NotionClient + WikiStore).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore, changed_since
from company_brain.agents.operations.notion import platform_config
from company_brain.agents.operations.shared.operations_slack import channel_notifier
from company_brain.config import AppConfig, load_config
from company_brain.notify import ACTIONABLE, Signal
from company_brain.notion.client import NotionClient
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore, WikiStore

REVIEW_PREFIX = "admin/notion-orphan-review/"
WEEK_KEY = "notion_orphan_discovery:week"
IGNORED_STATUS = frozenset({"ignore", "ignored", "archive", "archived"})


class OrphanDiscoveryAgent(BaseAgent):
    """Weekly Notion orphan crawl → admin review pages (never auto-adopt)."""

    name = "orphan_discovery"
    WRITE_MODE = UPDATE

    def __init__(
        self,
        config: AppConfig,
        *,
        store: WikiStore | None = None,
        client: NotionClient | None = None,
        state: StateStore | None = None,
        sync: bool = True,
        **kwargs: Any,
    ):
        super().__init__(config, **kwargs)
        self._store = store or LocalWikiStore()
        self._client = client or NotionClient()
        self._state = state or StateStore()
        self._sync = sync

    def should_run(self, **kwargs: Any) -> bool:
        if not platform_config.orphan_discovery_enabled():
            return False
        if kwargs.get("force"):
            return True
        week = _iso_week_key(datetime.now(timezone.utc))
        return changed_since(WEEK_KEY, week, store=self._state, update=False)

    def run(self, *, force: bool = False, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        if not self.should_run(force=force):
            return {"status": "skipped", "reason": "not_due"}

        roots = _teamspace_roots(self.config)
        if not roots:
            return {"status": "skipped", "reason": "no_teamspace_roots"}

        bound = collect_bound_notion_ids(self._store)
        # Roots themselves are expected mirrors — not orphans
        bound.update(roots.keys())
        ignored = collect_ignored_orphan_ids(self._store)

        pages = crawl_under_roots(self._client, set(roots.keys()))
        orphans: list[dict[str, Any]] = []
        written: list[str] = []

        for page in pages:
            page_id = str(page.get("page_id") or "").strip()
            if not page_id or page_id in bound or page_id in ignored:
                continue
            review_rel = orphan_review_path(page_id)
            if self._store.exists(review_rel):
                # Already queued — refresh body if still open
                try:
                    existing = self._store.read(review_rel)
                    status = str((existing.frontmatter or {}).get("orphan_status") or "open")
                    if status.lower() in IGNORED_STATUS:
                        continue
                except FileNotFoundError:
                    pass
            teamspace = roots.get(str(page.get("root_id") or ""), "unknown")
            rel = self._write_review(page, teamspace=teamspace)
            written.append(rel)
            orphans.append(page)

        week = _iso_week_key(datetime.now(timezone.utc))
        changed_since(WEEK_KEY, week, store=self._state, update=True)

        pinged = False
        if written:
            pinged = self._ping(len(written))

        return {
            "status": "ok",
            "orphans": len(orphans),
            "written": written,
            "roots": list(roots.values()),
            "pinged": pinged,
            "auto_adopted": 0,
        }

    def _write_review(self, page: dict[str, Any], *, teamspace: str) -> str:
        page_id = str(page["page_id"])
        title = str(page.get("title") or "(Untitled)")
        url = str(page.get("url") or _notion_url(page_id))
        rel = orphan_review_path(page_id)
        short = page_id.replace("-", "")[:12]
        body = "\n".join(
            [
                f"# Notion Orphan — {title}",
                "",
                f"**Notion page:** [{title}]({url})",
                f"**Page id:** `{page_id}`",
                f"**Teamspace root:** `{teamspace}`",
                f"**Discovered:** {datetime.now(timezone.utc).date().isoformat()}",
                "",
                "This page sits under a configured Notion teamspace root but has no "
                "Markdown `notion_page_id` binding in the company wiki.",
                "",
                "## Actions (human only — never auto-adopt)",
                "",
                "- **Adopt** — pull into MD under a chosen path (CLI / coding agent), "
                "then set frontmatter `orphan_status: adopted` on this review page.",
                "- **Ignore** — set `orphan_status: ignore` in this page's frontmatter "
                "(discovery will skip on later crawls).",
                "- **Archive** — archive in Notion, then set `orphan_status: archive`.",
                "",
                f"_Review id: `{short}`_",
                "",
            ]
        )
        write_wiki_page(
            rel,
            f"Notion Orphan — {title}",
            body,
            mode=UPDATE,
            section="admin",
            sync_label="admin_only",
            store=self._store,
            sync=self._sync,
            extra_frontmatter={
                "orphan_status": "open",
                "notion_orphan_page_id": page_id,
                "notion_orphan_url": url,
                "teamspace": teamspace,
                "source": "orphan_discovery",
            },
        )
        return rel

    def _ping(self, count: int) -> bool:
        text = (
            f"Notion orphan discovery found {count} unbound page(s). "
            f"Review under wiki `{REVIEW_PREFIX}` (Adopt / Ignore / Archive — never auto)."
        )
        try:
            channel = platform_config.orphan_discovery_admin_channel()
            return channel_notifier(channel).emit(Signal(text=text, severity=ACTIONABLE))
        except Exception:
            self.logger.exception("Orphan discovery Slack ping failed")
            return False


def orphan_review_path(page_id: str) -> str:
    slug = page_id.replace("-", "")[:24] or "unknown"
    return f"{REVIEW_PREFIX}{slug}.md"


def collect_bound_notion_ids(store: WikiStore) -> set[str]:
    bound: set[str] = set()
    for rel in store.list():
        if not rel.endswith(".md"):
            continue
        try:
            doc = store.read(rel)
        except FileNotFoundError:
            continue
        pid = str((doc.frontmatter or {}).get("notion_page_id") or "").strip()
        if pid:
            bound.add(pid)
            bound.add(pid.replace("-", ""))
    return bound


def collect_ignored_orphan_ids(store: WikiStore) -> set[str]:
    ignored: set[str] = set()
    for rel in store.list():
        if not rel.startswith(REVIEW_PREFIX) or not rel.endswith(".md"):
            continue
        try:
            doc = store.read(rel)
        except FileNotFoundError:
            continue
        fm = doc.frontmatter or {}
        status = str(fm.get("orphan_status") or "").lower()
        if status not in IGNORED_STATUS:
            continue
        pid = str(fm.get("notion_orphan_page_id") or "").strip()
        if pid:
            ignored.add(pid)
    return ignored


def crawl_under_roots(
    client: NotionClient,
    root_ids: set[str],
    *,
    max_pages: int = 500,
) -> list[dict[str, Any]]:
    """BFS child pages under each root. Pure discovery — no writes."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root_id in root_ids:
        queue: list[tuple[str, str]] = [(root_id, root_id)]
        while queue and len(found) < max_pages:
            current, root = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            try:
                children = client.get_block_children(current)
            except Exception:
                continue
            for block in children:
                if not isinstance(block, dict):
                    continue
                btype = str(block.get("type") or "")
                bid = str(block.get("id") or "").strip()
                if not bid:
                    continue
                if btype == "child_page":
                    title = ""
                    child = block.get("child_page") or {}
                    if isinstance(child, dict):
                        title = str(child.get("title") or "")
                    if bid != root_id:
                        found.append(
                            {
                                "page_id": bid,
                                "title": title or "(Untitled)",
                                "url": _notion_url(bid),
                                "root_id": root,
                            }
                        )
                    queue.append((bid, root))
                elif btype == "child_database":
                    # Do not treat databases as orphans; still walk? skip walk
                    continue
    return found


def _teamspace_roots(config: AppConfig | None = None) -> dict[str, str]:
    """Map parent page id → teamspace key for non-empty configured roots."""
    cfg = config or load_config()
    notion = cfg.notion
    out: dict[str, str] = {}
    teamspaces = dict(notion.teamspaces or {})
    for key, parent in teamspaces.items():
        pid = str(parent or "").strip()
        if pid:
            out[pid] = str(key)
    root = str(notion.root_page_id or "").strip()
    if root and root not in out:
        out[root] = "root"
    return out


def _notion_url(page_id: str) -> str:
    return f"https://www.notion.so/{page_id.replace('-', '')}"


def _iso_week_key(when: datetime) -> str:
    iso = when.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


__all__ = [
    "OrphanDiscoveryAgent",
    "REVIEW_PREFIX",
    "collect_bound_notion_ids",
    "crawl_under_roots",
    "orphan_review_path",
]
