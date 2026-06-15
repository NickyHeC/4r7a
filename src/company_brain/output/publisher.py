"""Publishes wiki articles to Notion pages."""

from __future__ import annotations

import logging

from company_brain.config import AppConfig
from company_brain.notion.client import NotionClient
from company_brain.output.formatter import format_article
from company_brain.wiki.article import Article
from company_brain.wiki.registry import PageRegistry

logger = logging.getLogger(__name__)


class Publisher:
    """Manages creating and updating Notion pages for wiki articles."""

    def __init__(
        self,
        client: NotionClient,
        config: AppConfig,
        registry: PageRegistry,
    ):
        self._client = client
        self._config = config
        self._registry = registry

    def publish(self, article: Article) -> str:
        """Publish an article to Notion. Creates or updates as needed.

        Returns the Notion page ID.
        """
        markdown = format_article(article, self._config.wiki)

        existing_page_id = (
            article.notion_page_id or self._registry.get_page_id(article.id)
        )

        if existing_page_id:
            return self._update(existing_page_id, article, markdown)
        return self._create(article, markdown)

    def publish_batch(self, articles: list[Article]) -> dict[str, str]:
        """Publish multiple articles. Returns mapping of article_id -> page_id."""
        results: dict[str, str] = {}
        for article in articles:
            try:
                page_id = self.publish(article)
                results[article.id] = page_id
            except Exception:
                logger.exception("Failed to publish article %s", article.id)
        return results

    def _create(self, article: Article, markdown: str) -> str:
        parent_id = self._resolve_parent(article)
        if not parent_id:
            raise ValueError(
                f"No Notion parent page for section '{article.section}'. "
                "Run 'company-brain init' first."
            )

        logger.info("Creating page for article '%s' under %s", article.title, parent_id)
        result = self._client.create_page(parent_id, markdown, title=article.title)

        page_id = _extract_page_id(result.stdout)
        if page_id:
            article.notion_page_id = page_id
            self._registry.register(article.id, page_id)
            logger.info("Created page %s for article '%s'", page_id, article.title)

        return page_id or ""

    def _update(self, page_id: str, article: Article, markdown: str) -> str:
        logger.info("Updating page %s for article '%s'", page_id, article.title)
        self._client.update_page(page_id, markdown)
        return page_id

    def _resolve_parent(self, article: Article) -> str | None:
        """Find the Notion page ID for the article's section."""
        section_id = self._config.notion.section_page_ids.get(article.section)
        if section_id:
            return section_id
        return self._registry.get_section_page_id(article.section)


def _extract_page_id(output: str) -> str | None:
    """Best-effort extraction of page ID from ntn pages create output."""
    import json as _json
    try:
        data = _json.loads(output)
        return data.get("id")
    except (_json.JSONDecodeError, AttributeError):
        pass

    for line in output.splitlines():
        stripped = line.strip()
        if len(stripped) == 36 and stripped.count("-") == 4:
            return stripped
        if "notion.so/" in stripped:
            parts = stripped.rstrip("/").split("/")
            candidate = parts[-1].split("-")[-1] if parts else ""
            if len(candidate) == 32:
                return candidate
    return None
