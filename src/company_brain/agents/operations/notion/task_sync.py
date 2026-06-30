"""Notion Task Sync Agent — create or update task database rows on propagation.

Writes status/title to the correct Notion database per binding routing config.
Used on ingest fan-out (Granola) and when Linear status changes.

SDK: Neither (Notion API via ``ntn``).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.linear.task_bindings import (
    TaskBinding,
    TaskBindingStore,
    attach_notion_platform,
)
from company_brain.agents.engineering.linear.task_propagate import (
    mark_propagated,
    record_status_change,
    should_propagate_field,
)
from company_brain.agents.engineering.shared.linear_config import task_class_fan_out
from company_brain.agents.operations.notion import db, task_config
from company_brain.config import AppConfig
from company_brain.notion.client import NotionClient


def linear_status_to_notion(status: str) -> str:
    """Map Linear workflow state names to Notion status column values."""
    normalized = (status or "").strip()
    if not normalized:
        return "Not started"
    lower = normalized.lower()
    if lower in {"done", "completed", "complete"}:
        return "Done"
    if lower in {"canceled", "cancelled"}:
        return "Canceled"
    if lower in {"in progress", "started"}:
        return "In progress"
    return normalized


class TaskSyncAgent(BaseAgent):
    """Ensure a binding has a Notion row and sync title/status from Linear."""

    name = "task_sync"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._bindings = TaskBindingStore()
        self._client = NotionClient()

    def should_run(self, **kwargs: Any) -> bool:
        return db.notion_is_available(self._client) and bool(
            task_config.configured_database_keys(notion=self.config.notion),
        )

    def run(
        self,
        *,
        binding: TaskBinding | None = None,
        task_id: str | None = None,
        linear_status: str | None = None,
        title: str | None = None,
        create_if_missing: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if binding is None and task_id:
            binding = self._bindings.get(task_id)
        if binding is None:
            return {"status": "skipped", "reason": "no_binding"}

        if "notion" not in task_class_fan_out(binding.task_class):
            return {"status": "skipped", "reason": "fan_out"}

        resolved = task_config.resolve_database_spec(
            binding.department,
            binding.project,
            notion=self.config.notion,
        )
        if resolved is None:
            return {"status": "skipped", "reason": "no_database"}

        db_key, spec = resolved
        notion_meta = binding.platforms.get("notion") or {}
        page_id = str(notion_meta.get("page_id") or "")

        if not page_id and create_if_missing:
            page = db.create_database_row(
                self._client,
                spec.database_id,
                spec=spec,
                title=title or binding.title or "Task",
                linear_identifier=binding.linear.get("identifier") or "",
                status=linear_status_to_notion(linear_status or ""),
            )
            page_id = str(page.get("id") or "")
            if not page_id:
                return {"status": "error", "reason": "create_failed"}
            binding = attach_notion_platform(
                binding,
                database_key=db_key,
                page_id=page_id,
                url=db.page_url(page),
            )
            self._bindings.upsert(binding, sync_notion=False)
            self._record_propagation(binding, linear_status)
            return {"status": "created", "page_id": page_id, "database_key": db_key}

        if not page_id:
            return {"status": "skipped", "reason": "no_page_id"}

        notion_status = linear_status_to_notion(linear_status) if linear_status else None
        patch_title = title
        if notion_status and not should_propagate_field(binding, "notion", "status", notion_status):
            return {"status": "skipped", "reason": "already_propagated"}

        db.update_database_row(
            self._client,
            page_id,
            spec=spec,
            database_id=spec.database_id,
            title=patch_title,
            status=notion_status,
            linear_identifier=binding.linear.get("identifier") or None,
        )
        self._record_propagation(binding, linear_status)
        return {"status": "updated", "page_id": page_id, "database_key": db_key}

    def _record_propagation(self, binding: TaskBinding, linear_status: str | None) -> None:
        if not linear_status:
            return
        notion_status = linear_status_to_notion(linear_status)
        record_status_change(
            binding,
            platform="notion",
            field="status",
            value=notion_status,
            source="system:task_propagate",
            store=self._bindings,
            mirror_wiki=False,
            propagate=False,
        )
        mark_propagated(
            binding,
            platform="notion",
            field="status",
            store=self._bindings,
            sync_notion=False,
        )
