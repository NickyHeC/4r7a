"""Trend watch — running page of relevant internet discussions for growth.

SDK: Neither for v1 (admin/instructions append). Selective #growth notify.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.shared.growth_slack import growth_notifier
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import APPEND, UPDATE, format_append_section, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

WIKI_PATH = "growth/content/trend-watch.md"
TITLE = "Trend Watch"
WRITE_MODE = UPDATE


class TrendWatchAgent(BaseAgent):
    """Append a trend item; notify when flagged actionable."""

    name = "trend_watch"
    WRITE_MODE = WRITE_MODE

    def run(
        self,
        *,
        summary: str,
        url: str = "",
        actionable: bool = False,
        notify: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        store = LocalWikiStore()
        if not store.exists(WIKI_PATH):
            write_wiki_page(
                WIKI_PATH,
                TITLE,
                f"# {TITLE}\n\nHot online discussions relevant to the company.\n",
                mode=WRITE_MODE,
                section="growth",
                type_="log",
            )
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        body = f"{summary.strip()}\n"
        if url:
            body += f"\n**Link:** {url}\n"
        section = format_append_section(day, body)
        write_wiki_page(
            WIKI_PATH,
            TITLE,
            section,
            mode=APPEND,
            section="growth",
            type_="log",
        )
        if actionable and notify:
            growth_notifier().emit(
                Signal(text=f"Trend watch: {summary.strip()[:200]}", severity=ACTIONABLE)
            )
        return {"status": "ok", "wiki_path": WIKI_PATH, "actionable": actionable}
