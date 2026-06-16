"""Publishes wiki articles: write Markdown (source of truth) then sync to Notion.

This is a thin wrapper that writes an Article to the WikiStore and mirrors it to
Notion via NotionSync. The Markdown file is authoritative; Notion is the mirror.
"""

from __future__ import annotations

import logging

from company_brain.config import AppConfig
from company_brain.notion.client import NotionClient
from company_brain.notion.sync import NotionSync
from company_brain.wiki.article import Article
from company_brain.wiki.index import WikiIndex
from company_brain.wiki.registry import PageRegistry
from company_brain.wiki.store import WikiStore

logger = logging.getLogger(__name__)


class Publisher:
    """Writes wiki articles MD-first, then mirrors them to Notion."""

    def __init__(
        self,
        client: NotionClient,
        config: AppConfig,
        registry: PageRegistry,
        store: WikiStore | None = None,
    ):
        self._index = WikiIndex(store)
        self._store = self._index.store
        self._sync = NotionSync(
            store=self._store, client=client, config=config, registry=registry
        )

    def publish(self, article: Article) -> str:
        """Write the article to the wiki store, then sync to Notion.

        Returns the Notion page ID (empty string if no parent was resolvable).
        """
        self._index.write_article(article)
        page_id = self._sync.sync_doc(article.rel_path())
        if page_id:
            article.notion_page_id = page_id
        return page_id or ""

    def publish_batch(self, articles: list[Article]) -> dict[str, str]:
        """Publish multiple articles. Returns mapping of article_id -> page_id."""
        results: dict[str, str] = {}
        for article in articles:
            try:
                results[article.id] = self.publish(article)
            except Exception:
                logger.exception("Failed to publish article %s", article.id)
        return results
