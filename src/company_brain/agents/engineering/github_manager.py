"""GitHub Manager Agent.

A manager agent: its duty is to dispatch other (specialist) agents based on the
information it gathers — it is not defined by its filename but by this role.
This manager is scoped to the GitHub platform within the engineering department.
A department may have several managers; each can cover one platform or span
multiple platforms.

SDK: Neither (pure orchestration) — persistent agent that idles and dispatches
specialist agents on schedule. Uses asyncio for the sleep loop and invokes
sub-agents directly.

Runs persistently. Checks GitHub on its configured schedule for relevant changes,
dispatching the appropriate specialist agents when needed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.config import AppConfig

logger = logging.getLogger(__name__)

MORNING_CHECK_TIME = time(8, 0)


class GitHubManager(BaseAgent):
    """Persistent manager that schedules and dispatches GitHub specialist agents."""

    name = "github_manager"

    def __init__(self, config: AppConfig, repo: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.repo = repo
        self._specialists: dict[str, type] = {}

    def register_specialist(self, key: str, agent_cls: type) -> None:
        """Register a specialist agent class for a dispatch key."""
        self._specialists[key] = agent_cls

    def _specialist_class(self, key: str) -> type | None:
        if key in self._specialists:
            return self._specialists[key]
        from company_brain.agents.engineering.github.branch_monitor import BranchMonitorAgent
        from company_brain.agents.engineering.github.feature_update import FeatureUpdateAgent
        from company_brain.agents.engineering.github.open_pr import OpenPRAgent
        from company_brain.agents.engineering.github.product_features import ProductFeaturesAgent

        return {
            "open_pr": OpenPRAgent,
            "feature_update": FeatureUpdateAgent,
            "product_features": ProductFeaturesAgent,
            "branch_monitor": BranchMonitorAgent,
        }.get(key)

    def run(self, **kwargs: Any) -> Any:
        """Start the persistent event loop."""
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        self.logger.info("GitHub manager starting persistent loop")
        while True:
            now = datetime.now()
            next_check = self._next_run_time(now)
            wait_seconds = (next_check - now).total_seconds()
            self.logger.info(
                "Next check at %s (sleeping %.0f seconds)", next_check.isoformat(), wait_seconds
            )
            await asyncio.sleep(wait_seconds)
            await self._morning_check()

    async def _morning_check(self) -> None:
        """Run the daily morning check and dispatch specialists as needed."""
        self.logger.info("Running morning GitHub check")
        today = datetime.now()
        is_monday = today.weekday() == 0

        # Branch status is refreshed every morning regardless of other activity.
        self._dispatch("branch_monitor")

        if self._has_open_pr_changes():
            self._dispatch("open_pr")

        if is_monday and self._has_commit_activity_this_week():
            self._dispatch("feature_update")

        if self._has_commit_activity_since_last_run():
            self._dispatch("product_features")

    def _dispatch(self, specialist_key: str) -> None:
        agent_cls = self._specialist_class(specialist_key)
        if not agent_cls:
            self.logger.warning("Specialist '%s' not registered", specialist_key)
            return
        self.logger.info("Dispatching specialist: %s", specialist_key)
        try:
            from company_brain.runtime import get_runtime

            get_runtime().run(agent_cls, self.config, repo=self.repo)
        except Exception:
            self.logger.exception("Specialist '%s' failed", specialist_key)

    def _has_open_pr_changes(self) -> bool:
        from company_brain.agents.engineering.github.gh import list_open_prs

        try:
            prs = list_open_prs(self.repo)
            return len(prs) > 0
        except Exception:
            self.logger.exception("Failed to check open PRs")
            return False

    def _has_commit_activity_this_week(self) -> bool:
        from company_brain.agents.engineering.github.gh import list_recent_commits

        since = (datetime.now() - timedelta(days=7)).isoformat()
        try:
            commits = list_recent_commits(self.repo, since=since)
            return len(commits) > 0
        except Exception:
            self.logger.exception("Failed to check weekly commits")
            return False

    def _has_commit_activity_since_last_run(self) -> bool:
        """Cost gate: only true when the latest commit advanced since last dispatch."""
        from company_brain.agents.engineering.github.gh import list_recent_commits
        from company_brain.agents.gates import changed_since

        since = (datetime.now() - timedelta(days=1)).isoformat()
        try:
            commits = list_recent_commits(self.repo, since=since)
            if not commits:
                return False
            latest = commits[0].get("sha", "") if commits else ""
            return changed_since(f"github:{self.repo}:last_commit", latest)
        except Exception:
            self.logger.exception("Failed to check recent commits")
            return False

    @staticmethod
    def _next_run_time(now: datetime) -> datetime:
        """Calculate the next 8am occurrence from now."""
        today_target = now.replace(
            hour=MORNING_CHECK_TIME.hour,
            minute=MORNING_CHECK_TIME.minute,
            second=0,
            microsecond=0,
        )
        if now >= today_target:
            return today_target + timedelta(days=1)
        return today_target
