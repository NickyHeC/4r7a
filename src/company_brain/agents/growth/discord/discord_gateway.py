"""Discord Gateway listener — WebSocket hot lane for community message ingest.

SDK: Neither (Gateway WebSocket + orchestration).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from company_brain.agents.growth.discord import discord_client
from company_brain.agents.growth.discord import discord_config as cfg
from company_brain.agents.growth.discord.events_router import (
    DiscordEventsRouter,
    sync_guild_channels,
)
from company_brain.config import AppConfig, load_config

logger = logging.getLogger(__name__)


def serve_gateway() -> None:
    """Start the Discord Gateway WebSocket listener (blocks until interrupted)."""
    if not discord_client.discord_is_configured():
        raise RuntimeError("DISCORD_BOT_TOKEN not set")

    config = load_config()
    guild_id = cfg.guild_id()
    if guild_id:
        stats = sync_guild_channels(guild_id)
        logger.info("Synced Discord channels: %s", stats)

    asyncio.run(_gateway_loop(config))


async def _gateway_loop(config: AppConfig) -> None:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "websockets package required for Discord Gateway — pip install websockets"
        ) from exc

    router = DiscordEventsRouter(config)
    url = discord_client.get_gateway_url()
    intents = cfg.gateway_intents()
    token = discord_client.bot_token()

    while True:
        try:
            async with websockets.connect(url, ping_interval=None) as ws:
                heartbeat_task: asyncio.Task[None] | None = None
                last_sequence: int | None = None
                logger.info("Discord Gateway connected")

                async for raw in ws:
                    payload = json.loads(raw)
                    op = payload.get("op")
                    event_type = payload.get("t")
                    data = payload.get("d") or {}

                    if payload.get("s") is not None:
                        last_sequence = payload["s"]

                    if op == 10:
                        interval_ms = int((data.get("heartbeat_interval") or 45000))
                        if heartbeat_task:
                            heartbeat_task.cancel()
                        heartbeat_task = asyncio.create_task(
                            _heartbeat(ws, interval_ms / 1000, lambda: last_sequence)
                        )
                        await ws.send(
                            json.dumps(
                                {
                                    "op": 2,
                                    "d": {
                                        "token": f"Bot {token}",
                                        "intents": intents,
                                        "properties": {
                                            "os": "company-brain",
                                            "browser": "company-brain",
                                            "device": "company-brain",
                                        },
                                    },
                                }
                            )
                        )
                        logger.info("Discord Gateway IDENTIFY sent (intents=%s)", intents)
                    elif op == 11:
                        continue
                    elif op == 0 and event_type == "READY":
                        logger.info(
                            "Discord Gateway READY (user=%s)",
                            (data.get("user") or {}).get("username"),
                        )
                    elif op == 0 and event_type:
                        try:
                            result = router.handle_dispatch(event_type, data)
                            logger.debug("Gateway %s: %s", event_type, result)
                        except Exception:
                            logger.exception("Gateway dispatch failed for %s", event_type)
                    elif op == 7:
                        logger.info("Discord Gateway reconnect requested")
                        break
                    elif op == 9:
                        logger.warning("Discord Gateway invalid session")
                        break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Discord Gateway connection error; retrying in 5s")
            await asyncio.sleep(5)


async def _heartbeat(
    ws: Any,
    interval_s: float,
    sequence_getter: Any,
) -> None:
    while True:
        await asyncio.sleep(interval_s)
        seq = sequence_getter()
        await ws.send(json.dumps({"op": 1, "d": seq}))
