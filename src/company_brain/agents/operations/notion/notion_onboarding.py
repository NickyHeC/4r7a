"""Notion Onboarding — alongside tree bootstrap with confirm-gated mirror.

Runs after MD wiki setup (early in install order):
- Existing messy Notion: **ingest → MD** always allowed; structured mirror/sync
  only after explicit ``confirm_mirror=True``.
- Empty workspace or confirmed: create alongside 4r7a structure (sections +
  Archive parents under admin/company), then hand off ``notion_manager``.

SDK: Neither (Notion discovery + WikiStore + runtime handoff).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.notion import db as notion_db
from company_brain.config import AppConfig, DiscoveryState, load_notion_config, save_notion_config
from company_brain.notion.client import NotionClient
from company_brain.notion.discovery import scan_workspace
from company_brain.notion.sync_routing import resolve_teamspace_parent
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc, WikiStore
from company_brain.wiki.taxonomy import classify_title, get_section_for_article_type

AGENT_KEY = "notion_onboarding"


class NotionOnboardingAgent(BaseAgent):
    """One-time Notion setup: ingest and/or alongside structure + manager handoff."""

    name = "notion_onboarding"

    def __init__(
        self,
        config: AppConfig,
        *,
        store: WikiStore | None = None,
        client: NotionClient | None = None,
        **kwargs: Any,
    ):
        super().__init__(config, **kwargs)
        self._store = store or LocalWikiStore()
        self._client = client or NotionClient()

    def should_run(self, **kwargs: Any) -> bool:
        return notion_db.notion_is_available(self._client)

    def run(
        self,
        *,
        confirm_mirror: bool = False,
        start_manager: bool = True,
        ingest_existing: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not notion_db.notion_is_available(self._client):
            return {"status": "not_configured"}

        report = scan_workspace(self._client, self.config.wiki)
        notion_cfg = load_notion_config()
        ingested = 0
        structure: dict[str, Any] | None = None

        if report.has_content and ingest_existing:
            ingested = self._ingest_pages(report.pages)

        mirror_enabled = False
        if not report.has_content:
            structure = self._build_alongside_structure(notion_cfg)
            mirror_enabled = True
        elif confirm_mirror:
            structure = self._build_alongside_structure(notion_cfg)
            mirror_enabled = True
        else:
            self.logger.warning(
                "Notion workspace has existing pages; mirror/sync NOT established "
                "(pass confirm_mirror=True after admin review). Ingest-only mode."
            )

        notion_cfg.discovery = DiscoveryState(
            strategy="alongside" if mirror_enabled else "ingest_only",
            scanned_at=report.scanned_at or datetime.now(timezone.utc).isoformat(),
            existing_page_count=report.total_pages,
            adopted_page_ids=[],
        )
        notion_cfg.mirror_enabled = mirror_enabled
        save_notion_config(notion_cfg)

        manager_started = False
        if start_manager and mirror_enabled:
            manager_started = self._start_manager()
        elif start_manager and not mirror_enabled:
            # Still start manager for pull/task loops; push skips unbound parents.
            manager_started = self._start_manager()

        return {
            "status": "ok",
            "existing_pages": report.total_pages,
            "ingested": ingested,
            "mirror_enabled": mirror_enabled,
            "structure": structure,
            "manager_started": manager_started,
        }

    def _ingest_pages(self, pages: list[Any]) -> int:
        count = 0
        now = datetime.now(timezone.utc).isoformat()
        for page in pages:
            title = (getattr(page, "title", None) or "Untitled").strip() or "Untitled"
            page_id = getattr(page, "page_id", "") or ""
            if not page_id:
                continue
            article_type = getattr(page, "classified_type", None) or classify_title(title)
            section = (
                get_section_for_article_type(article_type, self.config.wiki)
                if article_type
                else "operations/notion"
            )
            slug = _slugify(title)
            rel_path = f"{section}/{slug}.md" if section else f"operations/notion/ingest/{slug}.md"
            if self._store.exists(rel_path):
                rel_path = f"{section}/{slug}-{page_id[:8]}.md"

            body = f"# {title}\n\n"
            try:
                md, _edited = self._client.get_page_markdown(page_id)
                if md.strip():
                    # Drop duplicate H1 if present
                    body = md if md.lstrip().startswith("#") else f"# {title}\n\n{md}"
            except Exception:
                self.logger.debug("Could not fetch body for %s", page_id, exc_info=True)
                body = (
                    f"# {title}\n\n"
                    f"_Ingested from Notion onboarding; body unavailable at ingest time._\n"
                )

            fm = {
                "title": title,
                "section": section or "operations/notion",
                "notion_page_id": page_id,
                "ingested_from_notion": True,
                "created": now,
                "last_updated": now,
                "sources": [f"notion:{page_id}"],
            }
            # Ingest-only: do not push back to Notion
            self._store.write(rel_path, MarkdownDoc(frontmatter=fm, body=body))
            count += 1
        return count

    def _build_alongside_structure(self, notion_cfg: Any) -> dict[str, Any]:
        """Create Archive parents + section pages under teamspace roots."""
        created: dict[str, str] = {}
        teamspaces = notion_cfg.teamspaces or {}

        for ts_key in ("admin", "company"):
            parent = resolve_teamspace_parent(ts_key, self.config) or teamspaces.get(ts_key)
            parent = (parent or notion_cfg.root_page_id or "").strip()
            if not parent:
                self.logger.warning(
                    "No parent for teamspace %s — set teamspaces.%s or root_page_id",
                    ts_key,
                    ts_key,
                )
                continue

            archive_id = self._ensure_child_page(
                parent,
                title="Archive",
                body=(
                    f"# Archive\n\n"
                    f"Deprecated pages for the **{ts_key}** teamspace. "
                    f"MD wiki retains content.\n"
                ),
            )
            if archive_id:
                parents = dict(notion_cfg.archive_parents or {})
                parents[ts_key] = archive_id
                notion_cfg.archive_parents = parents
                created[f"archive:{ts_key}"] = archive_id

        for key, section in (self.config.wiki.sections or {}).items():
            ts = self.config.notion.teamspace_for_section(key) or "company"
            if ts == "admin_only":
                continue
            if ts not in {"admin", "company"}:
                ts = "company"
            if key in (notion_cfg.section_page_ids or {}):
                continue
            parent = resolve_teamspace_parent(ts, self.config) or (teamspaces.get(ts) or "")
            parent = (parent or notion_cfg.root_page_id or "").strip()
            if not parent:
                continue
            page_id = self._ensure_child_page(
                parent,
                title=section.label,
                body=f"# {section.label}\n\n{section.description or ''}\n",
            )
            if page_id:
                ids = dict(notion_cfg.section_page_ids or {})
                ids[key] = page_id
                notion_cfg.section_page_ids = ids
                created[f"section:{key}"] = page_id

        if not notion_cfg.root_page_id:
            company = (teamspaces.get("company") or "").strip()
            if company:
                notion_cfg.root_page_id = company

        return created

    def _ensure_child_page(self, parent_id: str, *, title: str, body: str) -> str:
        # Discover existing child by title search (best-effort)
        try:
            for page in self._client.search_all_pages():
                props = page.get("properties") or {}
                page_title = ""
                for prop in props.values():
                    if isinstance(prop, dict) and prop.get("type") == "title":
                        page_title = "".join(t.get("plain_text", "") for t in prop.get("title", []))
                        break
                if page_title.strip().lower() == title.strip().lower():
                    parent = page.get("parent") or {}
                    if parent.get("page_id") == parent_id or parent.get("workspace"):
                        return str(page.get("id") or "")
        except Exception:
            self.logger.debug("search during ensure_child failed", exc_info=True)

        result = self._client.create_page(parent_id, body, title=title)
        if result.json_data and isinstance(result.json_data, dict):
            return str(result.json_data.get("id") or "")
        return ""

    def _start_manager(self) -> bool:
        from company_brain.agents.operations.notion_manager import NotionManager
        from company_brain.runtime import get_runtime

        try:
            get_runtime().start(NotionManager, self.config)
            return True
        except Exception:
            self.logger.exception("Failed to start notion_manager")
            return False


def _slugify(title: str) -> str:
    import re

    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (s or "page")[:60]
