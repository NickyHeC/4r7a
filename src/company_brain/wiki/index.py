"""Wiki index: lookup articles by title, alias, or type.

The index is a derived, in-memory view over the Markdown wiki store (the source
of truth). ``load()`` scans the store's ``.md`` files into ``Article`` objects;
``save()`` writes each article back as Markdown and rebuilds the ``_index.md`` /
``_backlinks.json`` control files.
"""

from __future__ import annotations

import logging
from typing import Any

from company_brain.wiki import indexer
from company_brain.wiki.article import Article
from company_brain.wiki.store import LocalWikiStore, WikiStore

logger = logging.getLogger(__name__)

# Legacy filename kept for backward references; the store now owns persistence.
INDEX_FILENAME = "wiki_index.json"


class WikiIndex:
    """In-memory index of all wiki articles, backed by the Markdown WikiStore.

    Supports lookup by exact title, alias, article type, and fuzzy matching.
    """

    def __init__(self, store: WikiStore | None = None):
        self._store: WikiStore = store or LocalWikiStore()
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

    @property
    def store(self) -> WikiStore:
        return self._store

    def write_article(self, article: Article) -> None:
        """Persist a single article to the Markdown store (no index rebuild)."""
        self._store.write(article.rel_path(), article.to_doc())
        self.add(article)

    def rebuild_control_files(self) -> None:
        """Regenerate _index.md and _backlinks.json without rewriting articles."""
        indexer.rebuild(self._store, list(self._articles.values()), self._aliases)

    # -- Persistence ----------------------------------------------------------

    def save(self) -> None:
        """Write every article to Markdown and rebuild the control files."""
        for article in self._articles.values():
            self._store.write(article.rel_path(), article.to_doc())
        indexer.rebuild(self._store, list(self._articles.values()), self._aliases)
        logger.debug("Saved %d articles to wiki store", self.count)

    def load(self) -> None:
        """Scan the Markdown store into memory as Article objects."""
        self._articles = {}
        self._aliases = {}
        for rel_path in self._store.list():
            try:
                doc = self._store.read(rel_path)
            except Exception:
                logger.warning("Skipping unreadable wiki file: %s", rel_path)
                continue
            article = Article.from_doc(doc, rel_path)
            self._articles[article.id] = article
            for alias in (doc.frontmatter or {}).get("also", []) or []:
                self._aliases[str(alias).lower()] = article.id
        logger.debug("Loaded %d articles from wiki store", self.count)
