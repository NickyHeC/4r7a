"""Stale Review — flag active-but-idle pages onto the Conflict-adjacent review queue.

Does not archive. Appends to ``operations/notion/review.md`` and optionally creates
a Notion review DB row. See ``docs/plans/notion.md`` Session 6.

SDK: Neither (WikiStore + optional Notion DB).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.notion import db as notion_db
from company_brain.agents.operations.notion import platform_config
from company_brain.config import AppConfig, load_config
from company_brain.notion.archive_policy import is_stale_candidate
from company_brain.notion.client import NotionClient
from company_brain.wiki.publish import APPEND, format_append_section, write_wiki_page
from company_brain.wiki.store import CONTROL_FILES, LocalWikiStore, MarkdownDoc, WikiStore

logger = logging.getLogger(__name__)

WIKI_PATH = "operations/notion/review.md"
TITLE = "Notion Review"


def review_db_cfg() -> dict[str, Any]:
    return dict(load_config().notion.review_database or {})


def review_database_id() -> str:
    return str(review_db_cfg().get("database_id") or "").strip()


class StaleReviewAgent(BaseAgent):
    """Enqueue stale active pages for human review."""

    name = "stale_review"
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
        return True

    def run(self, **kwargs: Any) -> dict[str, Any]:
        flagged = 0
        stale_days = platform_config.stale_idle_days()
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
            if not is_stale_candidate(fm, stale_days=stale_days, now=now):
                continue

            title = str(fm.get("title") or rel_path)
            updated = str(fm.get("last_updated") or "")
            section = format_append_section(
                f"{now.date().isoformat()} — stale {title}",
                (
                    f"**Path:** `{rel_path}`\n"
                    f"**Last updated:** {updated or '(unknown)'}\n"
                    f"**Idle threshold:** {stale_days} days\n"
                    f"**Type:** stale_refresh\n"
                ),
                trigger="stale_review",
            )
            write_wiki_page(
                WIKI_PATH,
                TITLE,
                section,
                mode=APPEND,
                section="operations/notion",
                store=self._store,
                sync=self._sync,
            )
            row_id = self._maybe_create_review_row(title, rel_path)
            fm["stale_reviewed"] = True
            fm["stale_reviewed_at"] = now.isoformat()
            if row_id:
                fm["stale_review_notion_id"] = row_id
            self._store.write(rel_path, MarkdownDoc(frontmatter=fm, body=doc.body))
            flagged += 1

        return {"flagged": flagged}

    def _maybe_create_review_row(self, title: str, rel_path: str) -> str:
        db_id = review_database_id()
        if not db_id or not notion_db.notion_is_available(self._client):
            return ""
        cols = review_db_cfg().get("columns") or {}
        if not isinstance(cols, dict):
            cols = {}
        try:
            schema = notion_db.get_database_schema(self._client, db_id)
            properties: dict[str, Any] = {}
            properties.update(
                notion_db.build_property_patch(
                    str(cols.get("title") or "Title"),
                    f"Stale — {title}",
                    schema=schema,
                )
            )
            properties.update(
                notion_db.build_property_patch(
                    str(cols.get("status") or "Status"),
                    "open",
                    schema=schema,
                )
            )
            properties.update(
                notion_db.build_property_patch(
                    str(cols.get("rel_path") or "Path"),
                    rel_path,
                    schema=schema,
                )
            )
            properties.update(
                notion_db.build_property_patch(
                    str(cols.get("kind") or "Kind"),
                    "stale_refresh",
                    schema=schema,
                )
            )
            result = self._client.api(
                "v1/pages",
                method="POST",
                data=json.dumps({"parent": {"database_id": db_id}, "properties": properties}),
            )
            if result.json_data and isinstance(result.json_data, dict):
                return str(result.json_data.get("id") or "")
        except Exception:
            logger.exception("Failed to create review row for %s", rel_path)
        return ""
