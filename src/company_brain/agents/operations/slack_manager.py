"""Slack Manager — persistent dispatcher for Slack platform specialists.

Runs on ``slack_platform.poll_interval_minutes``. Each pass dispatches
``thread_watcher`` (poll backup) and ``channel_registry`` once per workday.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.operations.shared.scheduling import is_workday, next_interval
from company_brain.agents.operations.slack import slack_client
from company_brain.agents.operations.slack import slack_config as cfg
from company_brain.config import AppConfig

CHANNEL_REGISTRY_DAILY_KEY = "slack_manager:channel_registry_date"


class SlackManager(BaseAgent):
    """Persistent manager for the Slack platform within operations."""

    name = "slack_manager"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()

    def should_run(self, **kwargs: Any) -> bool:
        return slack_client.slack_is_configured()

    def run(self, **kwargs: Any) -> Any:
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        interval = cfg.poll_interval_minutes()
        self.logger.info("Slack manager starting (every %d min)", interval)
        while True:
            now = datetime.now()
            if not cfg.workdays_only() or is_workday(now):
                try:
                    await self._run_pass()
                except Exception:
                    self.logger.exception("Slack manager pass failed")
            nxt = next_interval(datetime.now(), interval, workdays_only=cfg.workdays_only())
            await asyncio.sleep(max((nxt - datetime.now()).total_seconds(), 60))

    async def _run_pass(self) -> None:
        from company_brain.agents.operations.slack.channel_registry import ChannelRegistryAgent
        from company_brain.agents.operations.slack.thread_watcher import ThreadWatcherAgent
        from company_brain.runtime import get_runtime

        runtime = get_runtime()
        self._run_agent(runtime, ThreadWatcherAgent, once=True)
        if self._should_run_channel_registry():
            self._run_agent(runtime, ChannelRegistryAgent)
            self._state.set(CHANNEL_REGISTRY_DAILY_KEY, datetime.now().date().isoformat())

    def _should_run_channel_registry(self) -> bool:
        today = datetime.now().date().isoformat()
        return self._state.get(CHANNEL_REGISTRY_DAILY_KEY) != today

    def _run_agent(self, runtime: Any, agent_cls: type, **kwargs: Any) -> None:
        try:
            runtime.run(agent_cls, self.config, **kwargs)
        except Exception:
            self.logger.exception("%s dispatch failed", agent_cls.__name__)
