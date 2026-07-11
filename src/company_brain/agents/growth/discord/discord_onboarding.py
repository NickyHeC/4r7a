"""Discord Onboarding — $0 estimate and operational backfill.

Runs once on first Discord connection: backfills routing records via
``ingest_triage`` + ``community_intake``, optional absorb on raw entries, then
starts ``discord_manager``. Run ``company-brain discord gateway`` separately
for the WebSocket hot lane.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.discord import channels_config, discord_client
from company_brain.agents.growth.discord import discord_config as cfg
from company_brain.agents.growth.discord.community_intake import CommunityIntakeAgent
from company_brain.agents.growth.discord.ingest_triage import IngestTriageAgent
from company_brain.agents.growth.discord.open_conversation import OpenConversationAgent
from company_brain.agents.growth.discord.technical_absorb import TechnicalAbsorbAgent

AGENT_KEY = "discord_onboarding"


class DiscordOnboardingAgent(BaseAgent):
    """One-time Discord setup: estimate, backfill ingest, hand off to manager."""

    name = "discord_onboarding"

    def run(
        self,
        *,
        start_manager: bool = True,
        backfill_days: int | None = None,
        all_history: bool = False,
        absorb: bool = False,
        estimate_only: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not discord_client.discord_is_configured():
            return {"status": "not_configured"}

        guild_id = cfg.guild_id()
        if guild_id:
            from company_brain.agents.growth.discord.events_router import sync_guild_channels

            sync_guild_channels(guild_id)

        days = (
            backfill_days if backfill_days is not None else cfg.onboarding_default_backfill_days()
        )
        estimate = estimate_backfill(
            days=days if not all_history else None,
            all_history=all_history,
        )
        if estimate_only:
            return {"status": "estimate", **estimate}

        if all_history:
            backfill_result = self._backfill_all()
        else:
            backfill_result = self._backfill_days(days)

        intake_result = CommunityIntakeAgent(self.config).run()
        open_result = OpenConversationAgent(self.config).run()

        absorb_result: dict[str, Any] | None = None
        if absorb:
            absorb_result = self._run_absorb_batch()

        manager_started = False
        if start_manager:
            self._start_manager()
            manager_started = True

        return {
            "status": "ok",
            "estimate": estimate,
            "backfill": backfill_result,
            "community_intake": intake_result,
            "open_conversation": open_result,
            "absorb": absorb_result,
            "manager_started": manager_started,
            "gateway_hint": "Run `company-brain discord gateway` for the WebSocket hot lane.",
        }

    def _backfill_days(self, days: int) -> dict[str, Any]:
        oldest = datetime.now(timezone.utc) - timedelta(days=days)
        return self._backfill_since(oldest)

    def _backfill_all(self) -> dict[str, Any]:
        return self._backfill_since(None)

    def _backfill_since(self, oldest: datetime | None) -> dict[str, Any]:
        triage = IngestTriageAgent(self.config)
        messages = 0
        routed = 0
        after = discord_client.datetime_to_snowflake_after(oldest) if oldest else None
        for channel in channels_config.list_text_channels():
            channel_id = str(channel.get("id") or "")
            if not channel_id:
                continue
            try:
                batch = discord_client.fetch_channel_messages(channel_id, after=after, limit=100)
            except discord_client.DiscordClientError:
                continue
            ch_type = int(channel.get("type", 0))
            for msg in batch:
                messages += 1
                result = triage.process_message(channel_id, msg, channel_type=ch_type)
                if result.get("status") == "routed":
                    routed += 1
        return {"messages": messages, "routed": routed}

    def _run_absorb_batch(self) -> dict[str, Any]:
        try:
            queue = TechnicalAbsorbAgent(self.config).run()
            from company_brain.wiki.absorb import AbsorbWriter

            writer = AbsorbWriter()
            absorb = writer.run()
            return {"queue": queue, "absorb": dict(absorb)}
        except Exception as exc:
            self.logger.warning("Optional absorb skipped: %s", exc)
            return {"status": "skipped", "reason": str(exc)}

    def _start_manager(self) -> None:
        from company_brain.agents.growth.discord_manager import DiscordManager
        from company_brain.runtime import get_runtime

        get_runtime().start(DiscordManager, self.config)


def estimate_backfill(*, days: int | None = 30, all_history: bool = False) -> dict[str, Any]:
    """$0 message count estimate for Discord onboarding."""
    if not discord_client.discord_is_configured():
        return {"status": "not_configured"}

    guild_id = cfg.guild_id()
    if guild_id:
        try:
            from company_brain.agents.growth.discord.events_router import sync_guild_channels

            sync_guild_channels(guild_id)
        except discord_client.DiscordClientError:
            pass

    message_count = 0
    channels_scanned = 0
    oldest = None
    if not all_history and days is not None:
        oldest = datetime.now(timezone.utc) - timedelta(days=days)
    after = discord_client.datetime_to_snowflake_after(oldest) if oldest else None

    channels = channels_config.list_text_channels()
    if not channels and guild_id:
        try:
            channels_config.sync_from_discord_api(discord_client.list_guild_channels(guild_id))
            channels = channels_config.list_text_channels()
        except discord_client.DiscordClientError:
            channels = []

    for channel in channels:
        channel_id = str(channel.get("id") or "")
        if not channel_id:
            continue
        channels_scanned += 1
        try:
            batch = discord_client.fetch_channel_messages(channel_id, after=after, limit=100)
        except discord_client.DiscordClientError:
            continue
        message_count += len(batch)

    return {
        "channels_scanned": channels_scanned,
        "message_count": message_count,
        "window_days": None if all_history else days,
        "token_estimate": 0,
    }
