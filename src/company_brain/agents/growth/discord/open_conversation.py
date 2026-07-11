"""Open Conversation tracker — company wiki snapshot of unresolved Discord threads.

SDK: Neither (routing record aggregation + wiki write).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.discord import discord_client
from company_brain.agents.growth.discord.routing import DiscordRoutingRecord, DiscordRoutingStore
from company_brain.config import AppConfig
from company_brain.members_config import load_members_config
from company_brain.wiki.publish import UPDATE, write_wiki_page

WIKI_PATH = "growth/discord/open-conversation.md"
TITLE = "Open Conversations"
OPEN_KINDS = {"discussion_pending", "technical_pending", "discussion_open"}


class OpenConversationAgent(BaseAgent):
    """Rebuild the company Discord open-conversation tracker page."""

    name = "discord_open_conversation"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._routing = DiscordRoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return discord_client.discord_is_configured()

    def run(self, **kwargs: Any) -> dict[str, Any]:
        records = list(self._open_records())
        body = render_open_conversations_body(records)
        write_wiki_page(
            WIKI_PATH,
            TITLE,
            body,
            mode=UPDATE,
            section="growth",
            type_="report",
        )
        return {"open_count": len(records), "wiki_path": WIKI_PATH}

    def _open_records(self) -> list[DiscordRoutingRecord]:
        team_ids = load_members_config().team_discord_ids()
        out: list[DiscordRoutingRecord] = []
        for record in self._routing.iter_open():
            if record.kind not in OPEN_KINDS:
                continue
            if record.handled.get("closed"):
                continue
            parent = record.parent_channel_id or record.channel_id
            if self._team_replied(parent, record.thread_id, team_ids):
                continue
            out.append(record)
        return out

    def _team_replied(self, parent: str, thread_id: str, team_ids: set[str]) -> bool:
        if not team_ids:
            return False
        try:
            authors = discord_client.conversation_author_ids(parent, thread_id)
            return bool(authors & team_ids)
        except discord_client.DiscordClientError:
            return False


def render_open_conversations_body(records: list[DiscordRoutingRecord]) -> str:
    if not records:
        return "_No open conversations._\n"

    lines = [
        f"_Updated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}_",
        "",
        "| Kind | Author | Preview | Link |",
        "| --- | --- | --- | --- |",
    ]
    for record in sorted(records, key=lambda r: r.updated_at, reverse=True):
        extracted = record.extracted or {}
        preview = str(extracted.get("text_preview") or "")[:120]
        link = str(extracted.get("permalink") or record.thread_id)
        author = str(extracted.get("author_handle") or "—")
        lines.append(f"| {record.kind or '—'} | {author} | {preview} | {link} |")
    lines.append("")
    return "\n".join(lines)
