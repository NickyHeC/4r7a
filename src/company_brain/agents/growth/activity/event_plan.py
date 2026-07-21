"""Assisted event planning — fill logistics checklist on the event page.

SDK: Neither (deterministic template merge). Uses existing page context from
register / Slack notes. LLM enrichment can be layered later.
"""

from __future__ import annotations

import re
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.activity.event_paths import event_rel_path
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

WRITE_MODE = UPDATE

LOGISTICS_BLOCK = """## Logistics

- **Venue:** _TBD — book early; confirm capacity, AV, cleanup, end time_
- **Registration:** Luma / Partiful — page, graphics, blast copy _(human-hosted; no API)_
- **Partners:** co-hosts / sponsors / speakers — roles and promo commitments
- **Merch:** inventory, packing list
- **Promotion:** X, LinkedIn, email — coordinate with partners
- **Travel:** see travel policy if out of town
"""


class EventPlanAgent(BaseAgent):
    """Expand planning sections on a registered event page."""

    name = "event_plan"
    WRITE_MODE = WRITE_MODE

    def run(self, *, slug: str, extra_notes: str = "", **kwargs: Any) -> dict[str, Any]:
        rel = event_rel_path(slug)
        store = LocalWikiStore()
        if not store.exists(rel):
            return {"status": "missing", "wiki_path": rel}

        doc = store.read(rel)
        title = str(doc.frontmatter.get("title") or slug)
        body = doc.body
        if "## Logistics" in body and "_Filled by assisted planning._" in body:
            body = body.replace(
                "## Logistics\n\n_Filled by assisted planning._\n",
                LOGISTICS_BLOCK + "\n",
            )
        elif "## Logistics" not in body:
            body = body.rstrip() + "\n\n" + LOGISTICS_BLOCK + "\n"

        if extra_notes.strip():
            body = _append_under_heading(body, "## Context", extra_notes.strip())

        fm = dict(doc.frontmatter)
        fm["event_status"] = "planning"
        write_wiki_page(
            rel,
            title,
            body,
            mode=WRITE_MODE,
            section="growth",
            type_="event",
            extra_frontmatter={
                "event_slug": fm.get("event_slug") or slug,
                "event_date": fm.get("event_date") or "",
                "event_status": "planning",
                "registered_via": fm.get("registered_via") or "",
            },
        )
        return {"status": "ok", "wiki_path": rel, "slug": slug}


def _append_under_heading(body: str, heading: str, text: str) -> str:
    if heading not in body:
        return body.rstrip() + f"\n\n{heading}\n\n{text}\n"
    pattern = re.compile(
        rf"({re.escape(heading)}\n)(.*?)(\n## |\Z)",
        re.DOTALL,
    )

    def repl(match: re.Match[str]) -> str:
        existing = match.group(2).rstrip()
        return f"{match.group(1)}{existing}\n\n{text}\n{match.group(3)}"

    return pattern.sub(repl, body, count=1)
