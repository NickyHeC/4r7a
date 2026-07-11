"""Discord Activity snapshot — channel and member activity metrics.

SDK: Neither (deterministic routing-record aggregation).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.discord import channels_config, discord_client
from company_brain.agents.growth.discord.routing import DiscordRoutingStore
from company_brain.config import AppConfig
from company_brain.wiki.publish import UPDATE, write_wiki_page

WIKI_PATH = "growth/discord/activity.md"
TITLE = "Discord Activity"


class ActivitySnapshotAgent(BaseAgent):
    """Rebuild Discord community activity metrics on the wiki."""

    name = "discord_activity_snapshot"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._routing = DiscordRoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return discord_client.discord_is_configured()

    def run(self, **kwargs: Any) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)
        week_records = 0
        month_records = 0
        authors_7d: set[str] = set()
        authors_30d: set[str] = set()
        channel_counts: Counter[str] = Counter()

        for record in self._routing.iter_all():
            updated = _parse_ts(record.updated_at)
            if updated and updated >= week_ago:
                week_records += 1
            if updated and updated >= month_ago:
                month_records += 1
            author = str((record.extracted or {}).get("author_id") or "")
            if author:
                if updated and updated >= week_ago:
                    authors_7d.add(author)
                if updated and updated >= month_ago:
                    authors_30d.add(author)
            channel = record.parent_channel_id or record.channel_id
            if updated and updated >= month_ago:
                channel_counts[channel] += 1

        body = _render_activity_body(
            week_records=week_records,
            month_records=month_records,
            authors_7d=len(authors_7d),
            authors_30d=len(authors_30d),
            channel_counts=channel_counts,
        )
        write_wiki_page(
            WIKI_PATH,
            TITLE,
            body,
            mode=UPDATE,
            section="growth",
            type_="report",
        )
        return {
            "wiki_path": WIKI_PATH,
            "records_7d": week_records,
            "records_30d": month_records,
        }


def _parse_ts(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _render_activity_body(
    *,
    week_records: int,
    month_records: int,
    authors_7d: int,
    authors_30d: int,
    channel_counts: Counter[str],
) -> str:
    lines = [
        f"_Updated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}_",
        "",
        "## Summary",
        "",
        f"- **Routing records (7d):** {week_records}",
        f"- **Routing records (30d):** {month_records}",
        f"- **Active authors (7d):** {authors_7d}",
        f"- **Active authors (30d):** {authors_30d}",
        "",
        "## Top channels (30d)",
        "",
    ]
    if not channel_counts:
        lines.append("_No channel activity yet._\n")
        return "\n".join(lines)
    lines.extend(["| Channel | Records |", "| --- | --- |"])
    for channel_id, count in channel_counts.most_common(15):
        name = channels_config.channel_name(channel_id)
        label = f"#{name}" if name != channel_id else channel_id
        lines.append(f"| {label} | {count} |")
    lines.append("")
    return "\n".join(lines)
