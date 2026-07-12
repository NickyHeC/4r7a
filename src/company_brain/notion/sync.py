"""NotionSync: mirror the Markdown wiki (source of truth) into Notion.

The wiki MD files are authoritative; Notion is a synced mirror. For each page,
sync compares the page's current body hash against the ``synced_hash``
recorded in frontmatter and skips unchanged pages (cheap gate). New pages are
discovered-or-created in Notion and the resulting ``notion_page_id`` is written
back into the frontmatter (the canonical binding), with the registry kept as a
derived cache.

Signature-gated push: when ``agent_signature`` matches the last pushed
signature and Notion has diverged (human edit), the push is skipped and MD is
restored from Notion (human wins locally; MD note only).

Control files (``_index.md``, ``_backlinks.json``, ``_absorb_log.json``) are
local-only and never mirrored.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from company_brain.config import AppConfig, load_config
from company_brain.notion.client import NotionClient
from company_brain.notion.sync_policy import (
    AGENT_SIGNATURE_KEY,
    PUSHED_AGENT_SIGNATURE_KEY,
    body_hash,
    should_skip_push_for_signature,
    stamp_agent_push,
    stamp_human_override,
)
from company_brain.notion.sync_routing import resolve_sync_parent, should_skip_notion_mirror
from company_brain.wiki.registry import PageRegistry
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc, WikiStore

logger = logging.getLogger(__name__)


class NotionSync:
    """Push changed wiki Markdown pages to Notion."""

    def __init__(
        self,
        store: WikiStore | None = None,
        client: NotionClient | None = None,
        config: AppConfig | None = None,
        registry: PageRegistry | None = None,
    ):
        self.store = store or LocalWikiStore()
        self.client = client or NotionClient()
        self.config = config or load_config()
        self.registry = registry or PageRegistry()
        if registry is None:
            self.registry.load()

    def sync_all(self) -> dict[str, str]:
        """Sync every content page in the store. Returns rel_path -> page_id."""
        results: dict[str, str] = {}
        for rel_path in self.store.list():
            try:
                page_id = self.sync_doc(rel_path)
                if page_id:
                    results[rel_path] = page_id
            except Exception:
                logger.exception("Failed to sync %s", rel_path)
        return results

    def sync_doc(
        self,
        rel_path: str,
        *,
        parent_id: str | None = None,
        force: bool = False,
    ) -> str | None:
        """Sync one wiki page to Notion; returns its Notion page id."""
        doc = self.store.read(rel_path)
        fm = dict(doc.frontmatter or {})
        title = fm.get("title") or rel_path.rsplit("/", 1)[-1].removesuffix(".md")
        current_hash = body_hash(doc.body)
        page_id = fm.get("notion_page_id")

        if should_skip_notion_mirror(fm, self.config):
            logger.info("Notion mirror skip: %s", rel_path)
            return None

        sync_parent = resolve_sync_parent(fm, self.config) if fm.get("sync") else None

        if page_id and not force and fm.get("synced_hash") == current_hash:
            logger.debug("Notion sync skip (unchanged): %s", rel_path)
            return page_id

        if not page_id:
            page_id = self._discover(title)

        if not page_id and not self.config.notion.is_mirror_enabled():
            logger.info(
                "Mirror disabled (notion_onboarding confirm pending) — skip create for %s",
                rel_path,
            )
            return None

        now = datetime.now(timezone.utc).isoformat()

        if page_id:
            notion_body = self._fetch_notion_body(page_id) if not force else None
            if not force and should_skip_push_for_signature(
                agent_signature=fm.get(AGENT_SIGNATURE_KEY),
                pushed_agent_signature=fm.get(PUSHED_AGENT_SIGNATURE_KEY),
                md_body=doc.body,
                notion_body=notion_body,
            ):
                logger.info(
                    "Signature-gated skip push for %s (human Notion edit preserved)",
                    rel_path,
                )
                self._apply_human_notion_body(
                    rel_path,
                    doc,
                    notion_body or "",
                    when_iso=now,
                    detail=(
                        "Human Notion edit preserved over agent re-push with "
                        f"unchanged signature {fm.get(AGENT_SIGNATURE_KEY)}"
                    ),
                )
                return page_id
            self.client.update_page(page_id, doc.body)
        else:
            page_id = self._create(doc, fm, title, sync_parent or parent_id)
            if not page_id:
                return None

        fm = stamp_agent_push(
            fm,
            signature=fm.get(AGENT_SIGNATURE_KEY),
            when_iso=now,
        )
        fm["notion_page_id"] = page_id
        fm["synced_hash"] = body_hash(doc.body)
        fm["last_synced"] = now
        doc.frontmatter = fm
        self.store.write(rel_path, doc)

        article_id = fm.get("id") or title
        try:
            self.registry.register(article_id, page_id)
            self.registry.save()
        except Exception:
            logger.debug("Registry update skipped for %s", rel_path)

        logger.info("Synced %s -> Notion %s", rel_path, page_id)
        return page_id

    def _fetch_notion_body(self, page_id: str) -> str | None:
        try:
            body, _edited = self.client.get_page_markdown(page_id)
            return body
        except Exception:
            logger.debug("Could not fetch Notion body for %s", page_id, exc_info=True)
            return None

    def _apply_human_notion_body(
        self,
        rel_path: str,
        doc: MarkdownDoc,
        notion_body: str,
        *,
        when_iso: str,
        detail: str,
    ) -> None:
        """Write Notion human content into MD; do not push back to Notion."""
        fm = stamp_human_override(dict(doc.frontmatter or {}), when_iso=when_iso, detail=detail)
        fm["synced_hash"] = body_hash(notion_body)
        fm["last_synced"] = when_iso
        fm["last_updated"] = when_iso
        updated = MarkdownDoc(frontmatter=fm, body=notion_body)
        self.store.write(rel_path, updated)

    # -- internals ---------------------------------------------------------

    def _create(self, doc: Any, fm: dict, title: str, parent_id: str | None) -> str | None:
        sync_parent = resolve_sync_parent(fm, self.config) if fm.get("sync") else None
        parent = parent_id or sync_parent or self._resolve_parent(fm.get("section", ""))
        if not parent:
            logger.warning(
                "No Notion parent for '%s' (section=%s); cannot create page. "
                "Run init or set a binding.",
                title,
                fm.get("section"),
            )
            return None
        result = self.client.create_page(parent, doc.body, title=title)
        return _extract_page_id(result.stdout, result.json_data)

    def _resolve_parent(self, section: str) -> str | None:
        # Route to the section's teamspace parent if configured (member reads are
        # enforced by Notion's teamspace permissions). Optional eng/product/growth
        # splits fall back to company when unset.
        from company_brain.notion.sync_routing import resolve_teamspace_parent

        ts_key = self.config.notion.teamspace_for_section(section)
        if ts_key and ts_key != "admin_only":
            ts_parent = resolve_teamspace_parent(ts_key, self.config)
            if ts_parent:
                return ts_parent
        if section:
            sid = self.config.notion.section_page_ids.get(section)
            if sid:
                return sid
            sid = self.registry.get_section_page_id(section)
            if sid:
                return sid
        return self.config.notion.root_page_id

    def _discover(self, title: str) -> str | None:
        """Best-effort: find an existing Notion page whose title matches."""
        try:
            pages = self.client.search_all_pages()
        except Exception:
            return None
        for page in pages:
            if _page_title(page).strip().lower() == title.strip().lower():
                return page.get("id")
        return None


def _page_title(page: dict[str, Any]) -> str:
    props = page.get("properties", {}) or {}
    for prop in props.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    return ""


def _extract_page_id(stdout: str, json_data: Any) -> str | None:
    if isinstance(json_data, dict) and json_data.get("id"):
        return json_data["id"]
    for line in (stdout or "").splitlines():
        s = line.strip()
        if len(s) == 36 and s.count("-") == 4:
            return s
    return None
