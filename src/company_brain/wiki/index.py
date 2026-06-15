"""Wiki index: lookup articles by title, alias, or type."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from company_brain.wiki.article import Article

logger = logging.getLogger(__name__)

INDEX_FILENAME = "wiki_index.json"


class WikiIndex:
    """In-memory index of all wiki articles, backed by a JSON file.

    Supports lookup by exact title, alias, article type, and fuzzy matching.
    """

    def __init__(self, index_path: Path | None = None):
        self._index_path = index_path
        self._articles: dict[str, Article] = {}
        self._aliases: dict[str, str] = {}  # alias -> article id

    @property
    def articles(self) -> dict[str, Article]:
        return dict(self._articles)

    @property
    def count(self) -> int:
        return len(self._articles)

    def add(self, article: Article, aliases: list[str] | None = None) -> None:
        self._articles[article.id] = article
        if aliases:
            for alias in aliases:
                self._aliases[alias.lower()] = article.id

    def remove(self, article_id: str) -> None:
        self._articles.pop(article_id, None)
        self._aliases = {k: v for k, v in self._aliases.items() if v != article_id}

    def get(self, article_id: str) -> Article | None:
        return self._articles.get(article_id)

    def get_by_title(self, title: str) -> Article | None:
        lower = title.lower()
        alias_id = self._aliases.get(lower)
        if alias_id:
            return self._articles.get(alias_id)
        for article in self._articles.values():
            if article.title.lower() == lower:
                return article
        return None

    def find_by_type(self, article_type: str) -> list[Article]:
        return [a for a in self._articles.values() if a.type == article_type]

    def find_by_section(self, section: str) -> list[Article]:
        return [a for a in self._articles.values() if a.section == section]

    def search(self, query: str, *, limit: int = 10) -> list[Article]:
        """Simple substring search across titles and aliases."""
        lower = query.lower()
        scored: list[tuple[int, Article]] = []

        for article in self._articles.values():
            score = 0
            if lower in article.title.lower():
                score += 2
            if lower == article.title.lower():
                score += 3
            if score > 0:
                scored.append((score, article))

        for alias, article_id in self._aliases.items():
            if lower in alias:
                article = self._articles.get(article_id)
                if article and not any(a.id == article.id for _, a in scored):
                    scored.append((1, article))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [article for _, article in scored[:limit]]

    def stats(self) -> dict[str, Any]:
        """Return summary statistics about the index."""
        by_section: dict[str, int] = {}
        by_type: dict[str, int] = {}
        stubs = 0
        published = 0

        for article in self._articles.values():
            by_section[article.section] = by_section.get(article.section, 0) + 1
            by_type[article.type] = by_type.get(article.type, 0) + 1
            if article.is_stub:
                stubs += 1
            if article.is_published:
                published += 1

        return {
            "total": self.count,
            "published": published,
            "stubs": stubs,
            "by_section": by_section,
            "by_type": by_type,
        }

    # -- Persistence ----------------------------------------------------------

    def save(self, path: Path | None = None) -> None:
        target = path or self._index_path
        if not target:
            raise ValueError("No index path configured")

        data = {
            "articles": {
                aid: a.model_dump(mode="json") for aid, a in self._articles.items()
            },
            "aliases": self._aliases,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.debug("Saved index with %d articles to %s", self.count, target)

    def load(self, path: Path | None = None) -> None:
        target = path or self._index_path
        if not target or not target.exists():
            return

        with open(target) as f:
            data = json.load(f)

        self._articles = {}
        for aid, adict in data.get("articles", {}).items():
            self._articles[aid] = Article(**adict)
        self._aliases = data.get("aliases", {})
        logger.debug("Loaded index with %d articles from %s", self.count, target)
