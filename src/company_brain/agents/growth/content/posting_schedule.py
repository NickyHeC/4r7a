"""Posting schedule coordinator — suggest spacing; never auto-post.

SDK: Neither (deterministic schedule page).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

WIKI_PATH = "growth/content/posting-schedule.md"
TITLE = "Posting Schedule"
WRITE_MODE = UPDATE


class PostingScheduleAgent(BaseAgent):
    """Rebuild the posting deliverables / spacing suggestion page from open drafts."""

    name = "posting_schedule"
    WRITE_MODE = WRITE_MODE

    def run(self, **kwargs: Any) -> dict[str, Any]:
        store = LocalWikiStore()
        drafts: list[tuple[str, str, str]] = []
        for rel in store.list("growth/content/draft/"):
            if not rel.endswith(".md"):
                continue
            doc = store.read(rel)
            if str(doc.frontmatter.get("status") or "draft") != "draft":
                continue
            drafts.append(
                (
                    rel,
                    str(doc.frontmatter.get("channel") or "?"),
                    str(doc.frontmatter.get("suggested_author") or "_unassigned_"),
                )
            )

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"_Updated {now}_",
            "",
            "Suggest founder/employee posting dates so content is spaced out. "
            "Agents never post — humans publish.",
            "",
            "## Open drafts",
            "",
        ]
        if not drafts:
            lines.append("_No open drafts._")
        else:
            lines.extend(["| Draft | Channel | Suggested author |", "| --- | --- | --- |"])
            for rel, channel, author in drafts:
                lines.append(f"| `{rel}` | {channel} | {author} |")
        lines.extend(
            [
                "",
                "## Cadence guidance",
                "",
                "- Founder X: about 1 post / 2–5 days",
                "- LinkedIn: about 2–3 posts / month",
                "- Company account: launches and larger announcements",
                "- Employee accounts: smaller / expertise posts",
                "",
                "Create Google Calendar events for bigger launches only after explicit confirm "
                "(CLI / console / `@wiki`), never silently.",
                "",
            ]
        )
        write_wiki_page(
            WIKI_PATH,
            TITLE,
            "\n".join(lines),
            mode=WRITE_MODE,
            section="growth",
            type_="schedule",
        )
        return {"status": "ok", "wiki_path": WIKI_PATH, "open_drafts": len(drafts)}
