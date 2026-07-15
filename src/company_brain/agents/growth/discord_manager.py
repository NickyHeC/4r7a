"""Discord Manager — persistent dispatcher for Discord platform specialists.

Runs on ``config/growth.yaml`` → ``discord.poll_interval_minutes``. Gateway
runs separately via ``company-brain discord gateway``.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.growth.discord import discord_client
from company_brain.agents.growth.discord import discord_config as cfg
from company_brain.config import AppConfig

ABSORB_DAY_KEY = "discord_manager:absorb_date"
ACTIVITY_DAY_KEY = "discord_manager:activity_date"
MEMBER_SCORING_MONTH_KEY = "discord_manager:member_scoring_month"


class DiscordManager(BaseAgent):
    """Persistent manager for the Discord platform within growth."""

    name = "discord_manager"
    track_duration = False

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()

    def should_run(self, **kwargs: Any) -> bool:
        return discord_client.discord_is_configured()

    def run(self, **kwargs: Any) -> Any:
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        interval = cfg.poll_interval_minutes()
        self.logger.info("Discord manager starting (every %d min)", interval)
        while True:
            try:
                await self._run_pass()
            except Exception:
                self.logger.exception("Discord manager pass failed")
            await asyncio.sleep(max(interval * 60, 60))

    async def _run_pass(self) -> None:
        from company_brain.agents.growth.discord.activity_snapshot import ActivitySnapshotAgent
        from company_brain.agents.growth.discord.community_intake import CommunityIntakeAgent
        from company_brain.agents.growth.discord.member_scoring import MemberScoringAgent
        from company_brain.agents.growth.discord.open_conversation import OpenConversationAgent
        from company_brain.agents.growth.discord.poll_watcher import PollWatcherAgent
        from company_brain.agents.growth.discord.technical_absorb import TechnicalAbsorbAgent
        from company_brain.runtime import get_runtime

        runtime = get_runtime()
        self._run_agent(runtime, PollWatcherAgent)
        self._run_agent(runtime, CommunityIntakeAgent)
        self._run_agent(runtime, OpenConversationAgent)
        if self._should_run_activity_snapshot():
            self._run_agent(runtime, ActivitySnapshotAgent)
            self._state.set(ACTIVITY_DAY_KEY, datetime.now(timezone.utc).date().isoformat())
        if self._should_run_technical_absorb():
            self._run_agent(runtime, TechnicalAbsorbAgent)
            self._state.set(ABSORB_DAY_KEY, datetime.now(timezone.utc).date().isoformat())
        if self._should_run_member_scoring():
            self._run_agent(runtime, MemberScoringAgent)
            self._state.set(MEMBER_SCORING_MONTH_KEY, datetime.now(timezone.utc).strftime("%Y-%m"))

    def _should_run_activity_snapshot(self) -> bool:
        today = datetime.now(timezone.utc).date().isoformat()
        return self._state.get(ACTIVITY_DAY_KEY) != today

    def _should_run_technical_absorb(self) -> bool:
        now = datetime.now(timezone.utc)
        if now.hour < cfg.absorb_batch_hour_utc():
            return False
        today = now.date().isoformat()
        return self._state.get(ABSORB_DAY_KEY) != today

    def _should_run_member_scoring(self) -> bool:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        return self._state.get(MEMBER_SCORING_MONTH_KEY) != month

    def _run_agent(self, runtime: Any, agent_cls: type, **kwargs: Any) -> None:
        try:
            runtime.run(agent_cls, self.config, **kwargs)
        except Exception:
            self.logger.exception("%s dispatch failed", agent_cls.__name__)
