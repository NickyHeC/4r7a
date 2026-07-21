"""Post-event wrap — action items, content draft stubs, lead research queue.

SDK: Neither (deterministic). Hands off to content drafts + leads queue; never posts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.activity.event_paths import event_rel_path
from company_brain.agents.growth.shared.growth_slack import growth_notifier
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

WRITE_MODE = UPDATE


class EventWrapAgent(BaseAgent):
    """Mark event wrapped; queue content drafts and optional lead research job."""

    name = "event_wrap"
    WRITE_MODE = WRITE_MODE

    def run(
        self,
        *,
        slug: str,
        attendees_csv: str = "",
        notify: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        rel = event_rel_path(slug)
        store = LocalWikiStore()
        if not store.exists(rel):
            return {"status": "missing", "wiki_path": rel}

        doc = store.read(rel)
        title = str(doc.frontmatter.get("title") or slug)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        wrap_section = "\n".join(
            [
                "## Wrap",
                "",
                f"_Wrapped {now}_",
                "",
                "### Post-mortem",
                "",
                "- What worked:",
                "- What didn't:",
                "- Actual vs expected attendance:",
                "- Cost notes:",
                "",
                "### Follow-up",
                "",
                "- Thank partners",
                "- Recap to attendees",
                "- Lead research queued (attendee CSV when provided)",
                "- Social drafts queued for content workstream",
                "",
            ]
        )
        body = doc.body
        if "## Wrap" in body:
            import re

            body = re.sub(
                r"## Wrap\n.*?(?=\n## |\Z)",
                wrap_section + "\n",
                body,
                count=1,
                flags=re.DOTALL,
            )
        else:
            body = body.rstrip() + "\n\n" + wrap_section + "\n"

        write_wiki_page(
            rel,
            title,
            body,
            mode=WRITE_MODE,
            section="growth",
            type_="event",
            extra_frontmatter={
                "event_slug": slug,
                "event_date": doc.frontmatter.get("event_date") or "",
                "event_status": "wrapped",
                "registered_via": doc.frontmatter.get("registered_via") or "",
            },
        )

        from company_brain.agents.growth.content.draft_writer import queue_event_social_drafts
        from company_brain.agents.growth.leads.queue import enqueue_lead_job

        drafts = queue_event_social_drafts(slug=slug, event_title=title)
        lead_job = None
        if attendees_csv.strip():
            lead_job = enqueue_lead_job(
                source="attendee_csv",
                label=f"event:{slug}",
                payload={"csv_text": attendees_csv, "event_slug": slug},
            )

        if notify:
            try:
                growth_notifier().emit(
                    Signal(
                        text=(
                            f"Event wrap ready: *{title}* — content drafts + lead follow-up queued"
                        ),
                        severity=ACTIONABLE,
                    )
                )
            except Exception as exc:
                self.logger.warning("growth notify skipped: %s", exc)
        return {
            "status": "ok",
            "wiki_path": rel,
            "drafts": drafts,
            "lead_job": lead_job,
        }
