"""Content draft helpers and draft-writer agent (never posts).

SDK: OpenAI Agents path preferred for prose when available; deterministic
templates otherwise.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.activity.event_paths import slugify_event
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

WRITE_MODE = UPDATE
DRAFT_DIR = "growth/content/draft"


def draft_rel_path(slug: str) -> str:
    return f"{DRAFT_DIR}/{slug}.md"


def queue_event_social_drafts(*, slug: str, event_title: str) -> list[str]:
    """Create stub X + LinkedIn post-event drafts for content_manager to fill."""
    paths: list[str] = []
    for channel, tone in (
        ("x", "short and witty"),
        ("linkedin", "longer and celebrative"),
    ):
        draft_slug = f"{slug}-{channel}-wrap"
        rel = draft_rel_path(draft_slug)
        store = LocalWikiStore()
        if store.exists(rel):
            paths.append(rel)
            continue
        title = f"Draft — {event_title} ({channel})"
        body = "\n".join(
            [
                f"_Queued after event `{slug}`_",
                "",
                f"**Channel:** {channel}",
                f"**Tone:** {tone}",
                "**Suggested author:** _allocate by expertise_",
                "",
                "## Draft",
                "",
                f"_TODO: write {channel} wrap post for {event_title}_",
                "",
            ]
        )
        write_wiki_page(
            rel,
            title,
            body,
            mode=WRITE_MODE,
            section="growth",
            type_="draft",
            extra_frontmatter={
                "channel": channel,
                "status": "draft",
                "source_event": slug,
                "suggested_author": "",
            },
        )
        paths.append(rel)
    return paths


class DraftWriterAgent(BaseAgent):
    """Fill or create a content draft page from instructions."""

    name = "draft_writer"
    WRITE_MODE = WRITE_MODE

    def run(
        self,
        *,
        channel: str = "blog",
        instructions: str = "",
        title: str = "",
        suggested_author: str = "",
        source_event: str = "",
        slug: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        channel = (channel or "blog").strip().lower()
        draft_slug = slug or slugify_event(title or instructions[:48] or f"{channel}-draft")
        if channel not in draft_slug:
            draft_slug = f"{draft_slug}-{channel}"
        rel = draft_rel_path(draft_slug)
        page_title = title or f"Draft — {draft_slug}"
        prose = _compose_draft(channel=channel, instructions=instructions, title=page_title)
        body = "\n".join(
            [
                f"_Drafted {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}_",
                "",
                f"**Channel:** {channel}",
                f"**Suggested author:** {suggested_author or '_TBD_'}",
                "",
                "## Draft",
                "",
                prose,
                "",
            ]
        )
        write_wiki_page(
            rel,
            page_title,
            body,
            mode=WRITE_MODE,
            section="growth",
            type_="draft",
            extra_frontmatter={
                "channel": channel,
                "status": "draft",
                "source_event": source_event,
                "suggested_author": suggested_author,
            },
        )
        return {"status": "ok", "wiki_path": rel, "slug": draft_slug}


def _compose_draft(*, channel: str, instructions: str, title: str) -> str:
    """Best-effort draft; falls back to structured outline without LLM."""
    try:
        from agents import Agent, Runner

        from company_brain.llm import openai_agents as oa

        agent = Agent(
            name="growth_draft_writer",
            instructions=(
                "You draft company content. Never invent trade secrets. "
                "Match channel norms: blog=formal informative; x=short witty; "
                "linkedin=celebrative longer. Output markdown body only."
            ),
            model=oa.make_model(),
        )
        prompt = f"Channel: {channel}\nTitle: {title}\nInstructions:\n{instructions}"
        result = Runner.run_sync(agent, prompt, run_config=oa.make_run_config())
        text = str(getattr(result, "final_output", "") or "").strip()
        if text:
            return text
    except Exception:
        pass

    if channel == "x":
        return f"{title}: {instructions.strip() or 'Ship note.'}"[:280]
    if channel == "linkedin":
        return (
            f"## {title}\n\n{instructions.strip() or '_Add celebration + context._'}\n\n"
            "We're grateful for everyone who joined us.\n"
        )
    fallback = instructions.strip() or (
        "_Compile technical notes from wiki + public repos; no trade secrets._"
    )
    return f"## {title}\n\n{fallback}\n"
