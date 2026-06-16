"""Rebuild the wiki control files: _index.md and _backlinks.json.

Following the wiki-gen skill, these are derived artifacts rebuilt only at the
end of a command (absorb/sync), never hand-edited. ``_index.md`` is the master
index used for matching during absorption and answering queries; it lists each
article with ``also:`` aliases. ``_backlinks.json`` is the reverse [[wikilink]]
index used to find which articles reference a topic.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from company_brain.wiki.article import Article
    from company_brain.wiki.store import WikiStore

INDEX_FILE = "_index.md"
BACKLINKS_FILE = "_backlinks.json"

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def rebuild(store: "WikiStore", articles: list["Article"],
            aliases: dict[str, str] | None = None) -> None:
    """Regenerate _index.md and _backlinks.json from the current articles."""
    store.write_text(INDEX_FILE, _build_index_md(articles, aliases or {}))
    store.write_text(BACKLINKS_FILE, json.dumps(_build_backlinks(articles), indent=2))


def _build_index_md(articles: list["Article"], aliases: dict[str, str]) -> str:
    # invert alias map: article_id -> [aliases]
    by_article: dict[str, list[str]] = defaultdict(list)
    for alias, aid in aliases.items():
        by_article[aid].append(alias)

    by_section: dict[str, list["Article"]] = defaultdict(list)
    for art in articles:
        by_section[art.section or "(unsorted)"].append(art)

    lines = ["# Wiki Index", "", f"{len(articles)} articles.", ""]
    for section in sorted(by_section):
        lines.append(f"## {section}")
        lines.append("")
        for art in sorted(by_section[section], key=lambda a: a.title.lower()):
            also = by_article.get(art.id, [])
            also_str = f" — also: {', '.join(sorted(also))}" if also else ""
            lines.append(f"- [[{art.title}]] (`{art.rel_path()}`){also_str}")
        lines.append("")
    return "\n".join(lines)


def _build_backlinks(articles: list["Article"]) -> dict[str, list[str]]:
    # Map title (lowercased) -> article id for resolving link targets.
    title_to_id = {art.title.lower(): art.id for art in articles}
    backlinks: dict[str, set[str]] = defaultdict(set)
    for art in articles:
        for raw in WIKILINK_RE.findall(art.content):
            target = raw.split("|", 1)[0].strip()
            target_id = title_to_id.get(target.lower(), target)
            if target_id != art.id:
                backlinks[target_id].add(art.id)
    return {k: sorted(v) for k, v in sorted(backlinks.items())}
