"""Trend watch — daily running page of relevant internet discussions for growth.

Checks once per day (cost-gated), appends a dated section to the Trend Watch page,
and notifies ``#growth`` selectively on items flagged actionable. Items may be
supplied by the caller (v1 house pattern, mirroring ``competitor_watch``); with no
items it writes a dated placeholder to fill from public sources.

SDK: Neither for v1 (append + selective notify).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.growth.shared.growth_slack import growth_notifier
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import APPEND, UPDATE, format_append_section, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

WIKI_PATH = "growth/content/trend-watch.md"
TITLE = "Trend Watch"
WRITE_MODE = UPDATE
DAY_KEY = "trend_watch:day"


class TrendWatchAgent(BaseAgent):
    """Daily trend log; notify selectively when items are flagged actionable."""

    name = "trend_watch"
    WRITE_MODE = WRITE_MODE

    def __init__(self, config, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()

    def should_run(self, *, force: bool = False, **kwargs: Any) -> bool:
        """Cost gate: check at most once per day (dedup re-fires)."""
        if force:
            return True
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._state.get(DAY_KEY) != day

    def run(
        self,
        *,
        summary: str = "",
        url: str = "",
        actionable: bool = False,
        items: list[dict[str, Any]] | None = None,
        notify: bool = True,
        force: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        entries: list[dict[str, Any]] = list(items or [])
        if summary.strip():
            entries.append({"summary": summary, "url": url, "actionable": actionable})

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
        if entries:
            lines: list[str] = []
            for e in entries:
                text = str(e.get("summary") or "").strip()
                if not text:
                    continue
                line = f"- {text}"
                link = str(e.get("url") or "").strip()
                if link:
                    line += f" ([link]({link}))"
                lines.append(line)
            body = "\n".join(lines) + "\n"
        else:
            body = "Relevant online discussions (fill from public sources).\n"

        section = format_append_section(day, body)
        write_wiki_page(
            WIKI_PATH,
            TITLE,
            section,
            mode=APPEND,
            section="growth",
            type_="log",
        )

        flagged = [e for e in entries if e.get("actionable")]
        if notify:
            for e in flagged:
                growth_notifier().emit(
                    Signal(
                        text=f"Trend watch: {str(e.get('summary') or '').strip()[:200]}",
                        severity=ACTIONABLE,
                    )
                )

        self._state.set(DAY_KEY, day)
        return {
            "status": "ok",
            "wiki_path": WIKI_PATH,
            "items": len(entries),
            "actionable": len(flagged),
        }
