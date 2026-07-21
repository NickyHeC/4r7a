"""Draft a partnership one-pager for a co-hosted event.

SDK: Neither (deterministic template). Collects partner fields onto the event
page and a partner brief page under the event slug.
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.activity.event_paths import event_rel_path
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

WRITE_MODE = UPDATE


class PartnershipBriefAgent(BaseAgent):
    """Write ``growth/activity/event/{slug}-partner-{partner_slug}.md`` + update event."""

    name = "partnership_brief"
    WRITE_MODE = WRITE_MODE

    def run(
        self,
        *,
        slug: str,
        partner_name: str,
        partner_bio: str = "",
        partner_email: str = "",
        logo_notes: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        event_path = event_rel_path(slug)
        store = LocalWikiStore()
        if not store.exists(event_path):
            return {"status": "missing", "wiki_path": event_path}

        from company_brain.agents.growth.activity.event_paths import slugify_event

        partner_slug = slugify_event(partner_name)
        brief_rel = f"growth/activity/event/{slug}-partner-{partner_slug}.md"
        title = f"Partner brief — {partner_name}"
        body = "\n".join(
            [
                f"# {title}",
                "",
                f"**Event:** [[{slug}]]",
                "",
                "## Company",
                "",
                f"- **Name:** {partner_name}",
                f"- **Email:** {partner_email or '_TBD_'}",
                f"- **Logo / assets:** {logo_notes or '_Collect before promo_'}",
                "",
                "## Bio",
                "",
                partner_bio.strip() or "_Paste partner bio._",
                "",
                "## Pre-event",
                "",
                "- Confirm co-host roles and promo commitments",
                "- Exchange logos and brand guidelines",
                "- Align blast copy and registration links",
                "",
                "## Post-event",
                "",
                "- Thank-you note and shared recap",
                "- Action items for both sides",
                "",
            ]
        )
        write_wiki_page(
            brief_rel,
            title,
            body,
            mode=WRITE_MODE,
            section="growth",
            type_="brief",
            extra_frontmatter={
                "event_slug": slug,
                "partner_slug": partner_slug,
            },
        )

        doc = store.read(event_path)
        event_title = str(doc.frontmatter.get("title") or slug)
        partners_line = f"- [[{slug}-partner-{partner_slug}]] — {partner_name}"
        if partners_line not in doc.body:
            new_body = doc.body.replace(
                "## Partners\n\n_None yet._\n",
                f"## Partners\n\n{partners_line}\n",
            )
            if new_body == doc.body:
                new_body = doc.body.rstrip() + f"\n\n## Partners\n\n{partners_line}\n"
            write_wiki_page(
                event_path,
                event_title,
                new_body,
                mode=WRITE_MODE,
                section="growth",
                type_="event",
                extra_frontmatter={
                    k: doc.frontmatter.get(k)
                    for k in ("event_slug", "event_date", "event_status", "registered_via")
                    if doc.frontmatter.get(k) is not None
                },
            )
        return {
            "status": "ok",
            "wiki_path": brief_rel,
            "event_path": event_path,
            "partner_slug": partner_slug,
        }
