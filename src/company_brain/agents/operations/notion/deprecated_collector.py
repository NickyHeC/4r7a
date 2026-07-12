"""Deprecated Collector — move Notion pages to Archive when fully eligible.

MD content is retained; Notion page is re-parented under the teamspace Archive
parent. Eligibility: no MD edits, done/end_date, no Notion edits, no shared link
(all required). See ``docs/plans/notion.md`` Session 6.

SDK: Neither (WikiStore + Notion API).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.notion import db as notion_db
from company_brain.agents.operations.notion import platform_config
from company_brain.config import AppConfig
from company_brain.notion.archive_policy import archive_eligibility
from company_brain.notion.client import NotionClient
from company_brain.notion.scoped_search import teamspace_key_for_page
from company_brain.wiki.store import CONTROL_FILES, LocalWikiStore, MarkdownDoc, WikiStore


class DeprecatedCollectorAgent(BaseAgent):
    """Archive Notion mirrors for pages that meet all eligibility conditions."""

    name = "deprecated_collector"

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
        return True

    def run(self, **kwargs: Any) -> dict[str, Any]:
        archived = 0
        skipped = 0
        idle = platform_config.archive_idle_days()
        now = datetime.now(timezone.utc)

        for rel_path in self._store.list():
            name = rel_path.rsplit("/", 1)[-1]
            if name in CONTROL_FILES:
                continue
            try:
                doc = self._store.read(rel_path)
            except FileNotFoundError:
                continue
            fm = dict(doc.frontmatter or {})
            page_id = str(fm.get("notion_page_id") or "").strip()
            notion_edited = None
            notion_meta: dict[str, Any] = {}
            if page_id and notion_db.notion_is_available(self._client):
                try:
                    notion_meta = self._client.get_page_meta(page_id)
                    notion_edited = str(notion_meta.get("last_edited_time") or "") or None
                except Exception:
                    self.logger.debug("meta fetch failed for %s", page_id, exc_info=True)

            decision = archive_eligibility(
                fm,
                notion_last_edited=notion_edited,
                notion_meta=notion_meta,
                idle_days=idle,
                now=now,
            )
            if not decision.eligible:
                skipped += 1
                continue

            if page_id and notion_db.notion_is_available(self._client):
                if not self._move_to_archive(rel_path, fm, page_id):
                    skipped += 1
                    continue

            fm["archived"] = True
            fm["archived_at"] = now.isoformat()
            fm["last_updated"] = now.isoformat()
            self._store.write(rel_path, MarkdownDoc(frontmatter=fm, body=doc.body))
            archived += 1
            self.logger.info("Archived %s", rel_path)

        return {"archived": archived, "skipped": skipped}

    def _move_to_archive(self, rel_path: str, fm: dict[str, Any], page_id: str) -> bool:
        fm_ctx = dict(fm)
        fm_ctx["_rel_path"] = rel_path
        ts = teamspace_key_for_page(fm_ctx, self.config)
        if ts not in {"admin", "company"}:
            ts = "admin" if ts == "admin" else "company"
        parents = self.config.notion.archive_parents or {}
        parent = str(parents.get(ts) or parents.get("company") or "").strip()
        if not parent:
            # Fall back: create under teamspace root if Archive parent unset
            parent = str((self.config.notion.teamspaces or {}).get(ts) or "").strip()
        if not parent:
            self.logger.warning("No Archive parent for teamspace %s (%s)", ts, rel_path)
            return False
        try:
            self._client.api(
                f"v1/pages/{page_id}",
                method="PATCH",
                data=json.dumps({"parent": {"page_id": parent}}),
            )
            return True
        except Exception:
            self.logger.exception("Failed to move %s to Archive", rel_path)
            return False
