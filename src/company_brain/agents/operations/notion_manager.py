"""Notion Manager — persistent dispatcher for the Notion platform.

Polls on ``notion_platform.poll_interval_minutes``. Each pass runs page sync,
``@wiki``, conflicts, page_system, archive/stale review, task scanner, CRM
Notion mirror, and Weave approval poll.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

import asyncio
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.notion import db as notion_db
from company_brain.agents.operations.notion import platform_config
from company_brain.config import AppConfig
from company_brain.notion.client import NotionClient


class NotionManager(BaseAgent):
    """Persistent manager for the Notion platform within operations."""

    name = "notion_manager"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._client = NotionClient()

    def should_run(self, **kwargs: Any) -> bool:
        return notion_db.notion_is_available(self._client)

    def run(self, *, once: bool = False, **kwargs: Any) -> Any:
        if once:
            return self.run_once()
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        interval = platform_config.poll_interval_minutes()
        self.logger.info("Notion manager starting (poll every %d min)", interval)
        while True:
            try:
                self.run_once()
            except Exception:
                self.logger.exception("Notion manager pass failed")
            await asyncio.sleep(max(interval * 60, 60))

    def run_once(self) -> dict[str, Any]:
        from company_brain.agents.admin.weave_triage import WeaveTriageAgent
        from company_brain.agents.operations.notion.conflict_apply import ConflictApplyAgent
        from company_brain.agents.operations.notion.conflict_resolution import (
            ConflictResolutionAgent,
        )
        from company_brain.agents.operations.notion.deprecated_collector import (
            DeprecatedCollectorAgent,
        )
        from company_brain.agents.operations.notion.page_system import PageSystemAgent
        from company_brain.agents.operations.notion.stale_review import StaleReviewAgent
        from company_brain.agents.operations.notion.sync_pull import SyncPullAgent
        from company_brain.agents.operations.notion.task_scanner import TaskScannerAgent
        from company_brain.agents.operations.notion.wiki_directive import WikiDirectiveAgent
        from company_brain.crm.notion_sync import sync_all_crm
        from company_brain.runtime import get_runtime

        runtime = get_runtime()
        results: dict[str, Any] = {}
        results["sync_pull"] = self._run_agent(runtime, SyncPullAgent)
        results["wiki_directive"] = self._run_agent(runtime, WikiDirectiveAgent)
        results["conflict_resolution"] = self._run_agent(runtime, ConflictResolutionAgent)
        results["conflict_apply"] = self._run_agent(runtime, ConflictApplyAgent)
        results["page_system"] = self._run_agent(runtime, PageSystemAgent)
        results["stale_review"] = self._run_agent(runtime, StaleReviewAgent)
        results["deprecated_collector"] = self._run_agent(runtime, DeprecatedCollectorAgent)
        results["task_scanner"] = self._run_agent(runtime, TaskScannerAgent, once=True)
        results["crm_sync"] = self._run_callable(
            "crm_sync",
            lambda: sync_all_crm(config=self.config),
        )
        results["weave_approvals"] = self._run_callable(
            "weave_approvals",
            lambda: WeaveTriageAgent(self.config).poll_approved_dispatch(),
        )
        return results

    def _run_agent(self, runtime: Any, agent_cls: type, **kwargs: Any) -> Any:
        try:
            return runtime.run(agent_cls, self.config, **kwargs)
        except Exception:
            self.logger.exception("%s dispatch failed", agent_cls.__name__)
            return None

    def _run_callable(self, label: str, fn: Any) -> Any:
        try:
            return fn()
        except Exception:
            self.logger.exception("%s dispatch failed", label)
            return None
