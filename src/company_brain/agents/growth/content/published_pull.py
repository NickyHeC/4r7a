"""Weekly pull of company-published content → docs + voice + retire drafts.

SDK: Neither (deterministic). v1 accepts admin-supplied published items
(URL + final text); does not post or require X API writes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.wiki.publish import APPEND, UPDATE, format_append_section, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

WRITE_MODE = APPEND
SEED_WRITE_MODE = UPDATE
STATUS_WRITE_MODE = UPDATE
CATALOG_PATH = "growth/content/published.md"
CATALOG_TITLE = "Published Company Content"
VOICE_PATH = "growth/content/voice/company.md"
VOICE_TITLE = "Company Voice"
WEEK_KEY = "content_published_pull:week"


class PublishedPullAgent(BaseAgent):
    """Ingest published posts, retire matching drafts, refresh company voice."""

    name = "published_pull"
    WRITE_MODE = WRITE_MODE
    SEED_WRITE_MODE = SEED_WRITE_MODE
    STATUS_WRITE_MODE = STATUS_WRITE_MODE

    def __init__(self, config, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()

    def should_run(self, **kwargs: Any) -> bool:
        if kwargs.get("force") or kwargs.get("items"):
            return True
        week = datetime.now(timezone.utc).strftime("%G-W%V")
        return self._state.get(WEEK_KEY) != week

    def run(
        self,
        *,
        items: list[dict[str, str]] | None = None,
        force: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        items = list(items or [])
        week = datetime.now(timezone.utc).strftime("%G-W%V")
        store = LocalWikiStore()
        retired: list[str] = []

        if items:
            _ensure_catalog()
            for item in items:
                url = str(item.get("url") or "").strip()
                text = str(item.get("text") or "").strip()
                channel = str(item.get("channel") or "unknown").strip()
                title = str(item.get("title") or channel).strip()
                section = format_append_section(
                    f"{title} ({channel})",
                    f"**URL:** {url or '_none_'}\n\n{text or '_No body provided._'}\n",
                )
                write_wiki_page(
                    CATALOG_PATH,
                    CATALOG_TITLE,
                    section,
                    mode=self.WRITE_MODE,
                    section="growth",
                    type_="catalog",
                )
                retired.extend(_retire_matching_drafts(store, channel=channel))
            _refresh_voice(items)

        self._state.set(WEEK_KEY, week)
        return {
            "status": "ok",
            "week": week,
            "ingested": len(items),
            "retired_drafts": retired,
        }


def _ensure_catalog() -> None:
    store = LocalWikiStore()
    if store.exists(CATALOG_PATH):
        return
    write_wiki_page(
        CATALOG_PATH,
        CATALOG_TITLE,
        f"# {CATALOG_TITLE}\n\nArchive of company-published public content.\n",
        mode=SEED_WRITE_MODE,
        section="growth",
        type_="catalog",
    )


def _retire_matching_drafts(store: LocalWikiStore, *, channel: str) -> list[str]:
    """Mark open drafts on the same channel as posted when a publish is recorded."""
    retired: list[str] = []
    prefix = "growth/content/draft/"
    for rel in store.list(prefix):
        if not rel.endswith(".md"):
            continue
        doc = store.read(rel)
        if str(doc.frontmatter.get("status") or "") != "draft":
            continue
        draft_channel = str(doc.frontmatter.get("channel") or "")
        if channel and draft_channel != channel:
            continue
        title = str(doc.frontmatter.get("title") or rel)
        write_wiki_page(
            rel,
            title,
            doc.body,
            mode=STATUS_WRITE_MODE,
            section="growth",
            type_="draft",
            extra_frontmatter={
                "channel": draft_channel,
                "source_event": doc.frontmatter.get("source_event") or "",
                "suggested_author": doc.frontmatter.get("suggested_author") or "",
                "status": "posted",
                "posted_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            },
        )
        retired.append(rel)
    return retired


def _refresh_voice(items: list[dict[str, str]]) -> None:
    store = LocalWikiStore()
    samples = []
    for item in items:
        text = str(item.get("text") or "").strip()
        if text:
            samples.append(f"- ({item.get('channel')}) {text[:240]}")
    block = "\n".join(samples) if samples else "_No new samples this week._"
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    section = format_append_section(
        f"Voice refresh {day}",
        f"Patterns observed from newly published company content:\n\n{block}\n",
    )
    if store.exists(VOICE_PATH):
        write_wiki_page(
            VOICE_PATH,
            VOICE_TITLE,
            section,
            mode=WRITE_MODE,
            section="growth",
            type_="voice",
        )
    else:
        write_wiki_page(
            VOICE_PATH,
            VOICE_TITLE,
            f"# {VOICE_TITLE}\n\nLiving notes on company public voice.\n\n{section}",
            mode=SEED_WRITE_MODE,
            section="growth",
            type_="voice",
        )
