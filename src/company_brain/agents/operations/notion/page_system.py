"""Page System — relocate misplaced human pages and expire move stubs.

Misplaced pages are human Notion/MD placements that belong elsewhere. Moves leave
a stub at the old path (deleted after ``stub_ttl_days``). Also cleans expired
stubs created by ``@wiki move`` / wiki_directive.

SDK: Neither (WikiStore + optional Notion parent update).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.notion import platform_config
from company_brain.config import AppConfig
from company_brain.notion.client import NotionClient
from company_brain.notion.relocate import relocate_page
from company_brain.notion.sync import NotionSync
from company_brain.notion.sync_routing import resolve_teamspace_parent
from company_brain.wiki.store import CONTROL_FILES, LocalWikiStore, MarkdownDoc, WikiStore


class PageSystemAgent(BaseAgent):
    """Relocate marked pages and delete expired stubs."""

    name = "page_system"

    def __init__(
        self,
        config: AppConfig,
        *,
        store: WikiStore | None = None,
        client: NotionClient | None = None,
        sync: bool = True,
        **kwargs: Any,
    ):
        super().__init__(config, **kwargs)
        self._store = store or LocalWikiStore()
        self._client = client or NotionClient()
        self._sync = sync

    def should_run(self, **kwargs: Any) -> bool:
        return True

    def run(self, **kwargs: Any) -> dict[str, Any]:
        relocated = 0
        stubs_removed = 0
        now = datetime.now(timezone.utc)

        for rel_path in list(self._store.list()):
            name = rel_path.rsplit("/", 1)[-1]
            if name in CONTROL_FILES:
                continue
            try:
                doc = self._store.read(rel_path)
            except FileNotFoundError:
                continue
            fm = dict(doc.frontmatter or {})

            if fm.get("stub"):
                if self._stub_expired(fm, now):
                    self._store.delete(rel_path)
                    stubs_removed += 1
                continue

            target = str(fm.get("page_relocate_to") or fm.get("misplaced_to") or "").strip()
            if target and target != rel_path:
                self._relocate(rel_path, doc, target, when=now)
                relocated += 1
                continue

            # After @wiki move, ensure Notion parent matches new section when possible.
            if fm.get("relocated_from") and fm.get("notion_page_id"):
                if self._ensure_notion_parent(rel_path, fm):
                    fm = dict(self._store.read(rel_path).frontmatter)
                    fm.pop("relocated_from", None)
                    self._store.write(
                        rel_path,
                        MarkdownDoc(frontmatter=fm, body=self._store.read(rel_path).body),
                    )

        return {"relocated": relocated, "stubs_removed": stubs_removed}

    def _stub_expired(self, fm: dict[str, Any], now: datetime) -> bool:
        raw = str(fm.get("stub_expires_at") or "").strip()
        if not raw:
            # Fall back: stub older than TTL from last_updated
            ttl = platform_config.stub_ttl_days()
            updated = str(fm.get("last_updated") or fm.get("created") or "")
            if not updated:
                return False
            try:
                created = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            except ValueError:
                return False
            return (now - created).days >= ttl
        try:
            expires = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return False
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now >= expires

    def _relocate(
        self,
        from_path: str,
        doc: MarkdownDoc,
        to_path: str,
        *,
        when: datetime,
    ) -> None:
        fm = dict(doc.frontmatter or {})
        title = str(fm.get("title") or PurePosixPath(to_path).stem)
        relocate_page(
            store=self._store,
            config=self.config,
            from_path=from_path,
            to_path=to_path,
            fm=fm,
            body=doc.body,
            title=title,
            when=when,
            sync=self._sync,
        )
        self._ensure_notion_parent(to_path, dict(self._store.read(to_path).frontmatter))

    def _ensure_notion_parent(self, rel_path: str, fm: dict[str, Any]) -> bool:
        page_id = str(fm.get("notion_page_id") or "").strip()
        if not page_id:
            return False
        section = str(fm.get("section") or PurePosixPath(rel_path).parent)
        if section == ".":
            section = ""
        ts_key = self.config.notion.teamspace_for_section(section) or "company"
        if ts_key == "admin_only":
            ts_key = "admin"
        parent = resolve_teamspace_parent(ts_key, self.config)
        if not parent:
            return False
        try:
            self._client.api(
                f"v1/pages/{page_id}",
                method="PATCH",
                data=json.dumps({"parent": {"page_id": parent}}),
            )
            if self._sync:
                NotionSync(store=self._store, client=self._client, config=self.config).sync_doc(
                    rel_path,
                    force=True,
                )
            return True
        except Exception:
            self.logger.exception("Failed to move Notion parent for %s", rel_path)
            return False
