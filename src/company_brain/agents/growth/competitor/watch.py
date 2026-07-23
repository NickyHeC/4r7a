"""Monthly watch of known competitors — append watch notes.

SDK: Neither for v1 (placeholder watch stamp). Selective notify for inspiration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.growth.shared.growth_slack import growth_notifier
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import APPEND, format_append_section, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

MONTH_KEY = "competitor_watch:month"
WRITE_MODE = APPEND


class CompetitorWatchAgent(BaseAgent):
    """Append a monthly watch section on each competitor page."""

    name = "competitor_watch"
    WRITE_MODE = WRITE_MODE

    def __init__(self, config, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()

    def should_run(self, **kwargs: Any) -> bool:
        if kwargs.get("force"):
            return True
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        return self._state.get(MONTH_KEY) != month

    def run(
        self,
        *,
        force: bool = False,
        inspiration: list[dict[str, str]] | None = None,
        notify: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        store = LocalWikiStore()
        watched = 0
        for rel in store.list("growth/competitor/"):
            if not rel.endswith(".md") or rel.endswith("/_index.md") or rel.endswith("_index.md"):
                continue
            if "/_index" in rel:
                continue
            name = rel.rsplit("/", 1)[-1]
            if name == "_index.md":
                continue
            doc = store.read(rel)
            title = str(doc.frontmatter.get("title") or name.removesuffix(".md"))
            section = format_append_section(
                f"Watch {month}",
                "Product / growth / social activity review (fill from public sources).\n\n"
                "- Growth moves:\n"
                "- Product moves:\n"
                "- Inspiration candidates:\n",
            )
            write_wiki_page(
                rel,
                title,
                section,
                mode=self.WRITE_MODE,
                section="growth",
                type_="competitor",
            )
            watched += 1

        for item in inspiration or []:
            if notify:
                growth_notifier().emit(
                    Signal(
                        text=f"Competitor inspiration: {item.get('summary', '')[:200]}",
                        severity=ACTIONABLE,
                    )
                )

        self._state.set(MONTH_KEY, month)
        return {"status": "ok", "month": month, "watched": watched}
