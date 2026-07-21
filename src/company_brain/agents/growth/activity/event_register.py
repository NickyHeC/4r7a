"""Register a company event (human-gated entrypoint).

SDK: Neither (deterministic wiki write). Creates the event page SoT; never
invents events from calendar alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.activity.event_paths import (
    INDEX_PATH,
    INDEX_TITLE,
    event_rel_path,
    event_title,
    slugify_event,
)
from company_brain.agents.growth.shared.growth_slack import growth_notifier
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

WRITE_MODE = UPDATE


class EventRegisterAgent(BaseAgent):
    """Create ``growth/activity/event/{slug}.md`` from admin/Slack/CLI input."""

    name = "event_register"
    WRITE_MODE = WRITE_MODE

    def run(
        self,
        *,
        name: str,
        date: str = "",
        format: str = "",
        notes: str = "",
        source: str = "cli",
        notify: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        slug = slugify_event(name)
        rel = event_rel_path(slug)
        store = LocalWikiStore()
        if store.exists(rel):
            return {"status": "exists", "wiki_path": rel, "slug": slug}

        title = event_title(name)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        body = _render_new_event(
            title=title,
            date=date,
            format=format,
            notes=notes,
            source=source,
            now=now,
        )
        write_wiki_page(
            rel,
            title,
            body,
            mode=WRITE_MODE,
            section="growth",
            type_="event",
            extra_frontmatter={
                "event_slug": slug,
                "event_date": date or "",
                "event_status": "registered",
                "registered_via": source,
            },
        )
        _upsert_index(slug, title, date)
        if notify:
            try:
                growth_notifier().emit(
                    Signal(
                        text=f"Event registered: *{title}* (`{slug}`) via {source}",
                        severity=ACTIONABLE,
                    )
                )
            except Exception as exc:
                self.logger.warning("growth notify skipped: %s", exc)
        return {"status": "ok", "wiki_path": rel, "slug": slug, "title": title}


def _render_new_event(
    *,
    title: str,
    date: str,
    format: str,
    notes: str,
    source: str,
    now: str,
) -> str:
    lines = [
        f"_Registered {now} via {source}_",
        "",
        "## Proposal",
        "",
        f"- **Name:** {title}",
        f"- **Date:** {date or '_TBD_'}",
        f"- **Format:** {format or '_TBD_'}",
        "- **Target audience:** _TBD_",
        "- **Expected headcount:** _TBD_",
        "- **Budget estimate:** _TBD_",
        "- **Success metrics:** _TBD_",
        "- **Owner:** _TBD_",
        "",
        "## Context",
        "",
        notes.strip() or "_No additional context._",
        "",
        "## Logistics",
        "",
        "_Filled by assisted planning._",
        "",
        "## Partners",
        "",
        "_None yet._",
        "",
        "## Action items",
        "",
        "_None yet._",
        "",
        "## Wrap",
        "",
        "_Pending event completion._",
        "",
    ]
    return "\n".join(lines)


def _upsert_index(slug: str, title: str, date: str) -> None:
    store = LocalWikiStore()
    line = f"- [[{slug}]] — {title}" + (f" ({date})" if date else "")
    if store.exists(INDEX_PATH):
        doc = store.read(INDEX_PATH)
        body = doc.body.rstrip() + "\n" + line + "\n"
    else:
        body = f"# {INDEX_TITLE}\n\nRegistered company events.\n\n{line}\n"
    write_wiki_page(
        INDEX_PATH,
        INDEX_TITLE,
        body,
        mode=UPDATE,
        section="growth",
        type_="index",
    )
