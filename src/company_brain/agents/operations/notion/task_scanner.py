"""Notion Task Scanner — discover updated task rows and link into ``task_bindings``.

Read-first: links existing Notion rows to bindings via the Linear ID column;
does not create Linear issues or duplicate rows.

SDK: Neither (Notion API via ``ntn``).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.linear.task_bindings import (
    TaskBindingStore,
    attach_notion_platform,
)
from company_brain.agents.gates import StateStore
from company_brain.agents.operations.notion import db, platform_config, task_config
from company_brain.config import AppConfig
from company_brain.notion.client import NotionClient

SCAN_STATE_PREFIX = "task_scanner:last_scan:"


class TaskScannerAgent(BaseAgent):
    """Poll configured Notion task databases and link rows to existing bindings."""

    name = "task_scanner"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._bindings = TaskBindingStore()
        self._state = StateStore()
        self._client = NotionClient()

    def should_run(self, **kwargs: Any) -> bool:
        return db.notion_is_available(self._client) and bool(
            task_config.configured_database_keys(notion=self.config.notion),
        )

    def run(self, *, once: bool = False, **kwargs: Any) -> Any:
        if once:
            return self.run_once()
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        interval = platform_config.poll_interval_minutes()
        self.logger.info("Notion task scanner starting (poll every %d min)", interval)
        while True:
            try:
                self.run_once()
            except Exception:
                self.logger.exception("Notion task scanner poll failed")
            await asyncio.sleep(max(interval * 60, 60))

    def run_once(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        linked = 0
        scanned = 0
        for db_key in task_config.configured_database_keys(notion=self.config.notion):
            spec = self.config.notion.task_databases[db_key]
            since = self._since_timestamp(db_key, now)
            try:
                rows = db.query_database_updated_since(
                    self._client,
                    spec.database_id,
                    since,
                )
            except Exception:
                self.logger.exception("Notion query failed for database %s", db_key)
                continue
            scanned += len(rows)
            for row in rows:
                if self._link_row(db_key, row, spec):
                    linked += 1
            self._state.set(f"{SCAN_STATE_PREFIX}{db_key}", now.isoformat())

        return {"scanned": scanned, "linked": linked}

    def _since_timestamp(self, db_key: str, now: datetime) -> str:
        raw = self._state.get(f"{SCAN_STATE_PREFIX}{db_key}")
        if raw:
            try:
                return datetime.fromisoformat(raw).astimezone(timezone.utc).isoformat()
            except ValueError:
                pass
        return (now - timedelta(hours=24)).isoformat()

    def _link_row(
        self,
        db_key: str,
        row: dict[str, Any],
        spec: Any,
    ) -> bool:
        page_id = str(row.get("id") or "")
        if not page_id:
            return False
        if self._bindings.find_by_notion_page(page_id):
            return False

        fields = db.read_row_fields(row, spec)
        linear_ref = (fields.get("linear") or "").strip()
        if not linear_ref:
            return False

        binding = self._bindings.find_by_linear(linear_ref)
        if binding is None:
            return False

        existing = binding.platforms.get("notion") or {}
        if existing.get("page_id") == page_id:
            return False

        updated = attach_notion_platform(
            binding,
            database_key=db_key,
            page_id=page_id,
            url=db.page_url(row),
            title=fields.get("title") or binding.title,
        )
        self._bindings.upsert(updated, sync_notion=False)
        return True
