"""Monthly competitor discovery from company core-product keywords.

SDK: Neither for v1 seed/index maintenance. Keyword search is config-driven;
web search hooks can be added when an allow-listed tool is available.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.growth.shared.workstream_config import competitor_keywords
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

INDEX_PATH = "growth/competitor/_index.md"
INDEX_TITLE = "Competitors"
MONTH_KEY = "competitor_discover:month"
WRITE_MODE = UPDATE


class CompetitorDiscoverAgent(BaseAgent):
    """Ensure competitor index exists; record a monthly discovery pass from keywords."""

    name = "competitor_discover"
    WRITE_MODE = WRITE_MODE

    def __init__(self, config, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()

    def should_run(self, **kwargs: Any) -> bool:
        if kwargs.get("force"):
            return True
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        return self._state.get(MONTH_KEY) != month

    def run(self, *, force: bool = False, **kwargs: Any) -> dict[str, Any]:
        keywords = competitor_keywords()
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        store = LocalWikiStore()
        if not store.exists(INDEX_PATH):
            _write_index([], keywords, note="Initial index from company core-product keywords.")
        else:
            doc = store.read(INDEX_PATH)
            body = doc.body.rstrip()
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            kw = ", ".join(keywords) if keywords else "_none configured_"
            body += (
                f"\n\n## Discovery pass {month}\n\n"
                f"_Ran {stamp}_\n\n"
                f"**Keywords:** {kw}\n\n"
                "Search for products matching the company description using these keywords. "
                "Add new competitor pages under `growth/competitor/{slug}.md` when a match is "
                "confirmed by growth.\n"
            )
            write_wiki_page(
                INDEX_PATH,
                INDEX_TITLE,
                body,
                mode=WRITE_MODE,
                section="growth",
                type_="index",
            )

        # Seed placeholder pages for keyword tokens that look like product names (admin-filled).
        seeded = 0
        for kw in keywords:
            slug = _slug(kw)
            rel = f"growth/competitor/{slug}.md"
            if store.exists(rel) or slug in {"_index"}:
                continue
            write_wiki_page(
                rel,
                kw.title(),
                _competitor_stub(kw.title(), keywords),
                mode=WRITE_MODE,
                section="growth",
                type_="competitor",
                extra_frontmatter={"competitor_slug": slug, "status": "candidate"},
            )
            seeded += 1
            _ensure_index_link(slug, kw.title())

        self._state.set(MONTH_KEY, month)
        return {
            "status": "ok",
            "month": month,
            "keywords": keywords,
            "seeded": seeded,
        }


def _slug(name: str) -> str:
    from company_brain.agents.growth.activity.event_paths import slugify_event

    return slugify_event(name)


def _competitor_stub(title: str, keywords: list[str]) -> str:
    return "\n".join(
        [
            f"_Candidate from keywords: {', '.join(keywords) or 'n/a'}_",
            "",
            "## Bio",
            "",
            "_Fill product description._",
            "",
            "## Inspiration",
            "",
            "_Ideas / approaches worth noting._",
            "",
            "## Watch log",
            "",
            "_Monthly watch appends here._",
            "",
        ]
    )


def _write_index(rows: list[tuple[str, str]], keywords: list[str], *, note: str) -> None:
    lines = [
        f"# {INDEX_TITLE}",
        "",
        note,
        "",
        (
            "**Core keywords:** "
            + (", ".join(keywords) if keywords else "_configure growth.competitor.keywords_")
        ),
        "",
        "## List",
        "",
    ]
    for slug, title in rows:
        lines.append(f"- [[{slug}]] — {title}")
    if not rows:
        lines.append("_No confirmed competitors yet._")
    lines.append("")
    write_wiki_page(
        INDEX_PATH,
        INDEX_TITLE,
        "\n".join(lines),
        mode=WRITE_MODE,
        section="growth",
        type_="index",
    )


def _ensure_index_link(slug: str, title: str) -> None:
    store = LocalWikiStore()
    if not store.exists(INDEX_PATH):
        _write_index([(slug, title)], competitor_keywords(), note="Competitor index.")
        return
    doc = store.read(INDEX_PATH)
    line = f"- [[{slug}]] — {title}"
    if line in doc.body:
        return
    body = doc.body.replace(
        "_No confirmed competitors yet._\n",
        f"{line}\n",
    )
    if body == doc.body:
        body = doc.body.rstrip() + f"\n{line}\n"
    write_wiki_page(
        INDEX_PATH,
        INDEX_TITLE,
        body,
        mode=WRITE_MODE,
        section="growth",
        type_="index",
    )
