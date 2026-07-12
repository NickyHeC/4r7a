"""Conflict Apply — apply admin-chosen winners from the Conflict Resolutions Notion DB.

Admin sets Status to ``resolved_md`` or ``resolved_notion``; this agent writes MD
(then NotionSync) and marks the row ``applied``.

SDK: Neither (Notion DB + WikiStore).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.notion import conflict_store as store_mod
from company_brain.agents.operations.notion import db as notion_db
from company_brain.config import AppConfig
from company_brain.notion.client import NotionClient
from company_brain.notion.sync import NotionSync
from company_brain.notion.sync_policy import SYNC_CONFLICT_KEY, body_hash
from company_brain.wiki.publish import APPEND, format_append_section, write_wiki_page
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc, WikiStore


class ConflictApplyAgent(BaseAgent):
    """Apply admin resolutions from the Conflict Resolutions database."""

    name = "conflict_apply"
    WRITE_MODE = APPEND

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
        return store_mod.notion_db_available(self._client) or bool(kwargs.get("rows"))

    def run(self, *, rows: list[dict[str, Any]] | None = None, **kwargs: Any) -> dict[str, Any]:
        applied = 0
        errors = 0
        pending = rows
        if pending is None:
            if not notion_db.notion_is_available(self._client):
                return {"applied": 0, "errors": 0}
            pending = store_mod.query_resolved_rows(self._client)

        for row in pending:
            try:
                if self._apply_row(row):
                    applied += 1
            except Exception:
                self.logger.exception("conflict_apply failed for row")
                errors += 1
        return {"applied": applied, "errors": errors}

    def _apply_row(self, row: dict[str, Any]) -> bool:
        fields = store_mod.read_conflict_fields(row)
        rel_path = (fields.get("rel_path") or "").strip()
        status = (fields.get("status") or "").strip()
        if not rel_path or not self._store.exists(rel_path):
            self.logger.warning("conflict_apply missing path %s", rel_path)
            return False

        doc = self._store.read(rel_path)
        fm = dict(doc.frontmatter or {})
        now = datetime.now(timezone.utc).isoformat()

        if status == store_mod.STATUS_RESOLVED_MD:
            body = doc.body
            via = "admin_md"
        elif status == store_mod.STATUS_RESOLVED_NOTION:
            body = str(fm.get("conflict_notion_body") or "")
            if not body:
                page_id = str(fm.get("notion_page_id") or "").strip()
                if page_id:
                    body, _ = self._client.get_page_markdown(page_id)
            if not body:
                self.logger.warning("No Notion body to apply for %s", rel_path)
                return False
            via = "admin_notion"
        else:
            return False

        fm.pop(SYNC_CONFLICT_KEY, None)
        fm.pop("conflict_enqueued", None)
        fm.pop("conflict_notion_body", None)
        fm["synced_hash"] = body_hash(body)
        fm["last_synced"] = now
        fm["last_updated"] = now
        fm["conflict_resolved_via"] = via
        self._store.write(rel_path, MarkdownDoc(frontmatter=fm, body=body))

        if self._sync:
            NotionSync(store=self._store, client=self._client, config=self.config).sync_doc(
                rel_path,
                force=True,
            )

        page_id = str(row.get("id") or "")
        if page_id and store_mod.database_id():
            store_mod.mark_row_applied(page_id, client=self._client)

        title = str(fm.get("title") or rel_path)
        section = format_append_section(
            f"{now[:10]} — applied {title}",
            f"**Path:** `{rel_path}`\n**Via:** {via}\n**Status was:** {status}\n",
            trigger="conflict_apply",
        )
        write_wiki_page(
            store_mod.WIKI_PATH,
            store_mod.TITLE,
            section,
            mode=APPEND,
            section="operations/notion",
            store=self._store,
            sync=self._sync,
        )
        return True
