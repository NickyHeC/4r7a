"""Page registry: maps local article IDs to Notion page IDs."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

REGISTRY_FILENAME = "registry.json"


class PageRegistry:
    """Bidirectional mapping between article IDs and Notion page IDs.

    Persisted as a JSON file in the project root.
    """

    def __init__(self, registry_path: Path | None = None):
        self._path = registry_path
        self._article_to_page: dict[str, str] = {}
        self._page_to_article: dict[str, str] = {}
        self._section_pages: dict[str, str] = {}

    @property
    def count(self) -> int:
        return len(self._article_to_page)

    def register(self, article_id: str, notion_page_id: str) -> None:
        self._article_to_page[article_id] = notion_page_id
        self._page_to_article[notion_page_id] = article_id

    def unregister(self, article_id: str) -> None:
        page_id = self._article_to_page.pop(article_id, None)
        if page_id:
            self._page_to_article.pop(page_id, None)

    def get_page_id(self, article_id: str) -> str | None:
        return self._article_to_page.get(article_id)

    def get_article_id(self, notion_page_id: str) -> str | None:
        return self._page_to_article.get(notion_page_id)

    def has_article(self, article_id: str) -> bool:
        return article_id in self._article_to_page

    def has_page(self, notion_page_id: str) -> bool:
        return notion_page_id in self._page_to_article

    def all_article_ids(self) -> list[str]:
        return list(self._article_to_page.keys())

    def all_page_ids(self) -> list[str]:
        return list(self._page_to_article.keys())

    # -- Section pages --------------------------------------------------------

    def register_section(self, section_key: str, notion_page_id: str) -> None:
        self._section_pages[section_key] = notion_page_id

    def get_section_page_id(self, section_key: str) -> str | None:
        return self._section_pages.get(section_key)

    # -- Persistence ----------------------------------------------------------

    def save(self, path: Path | None = None) -> None:
        target = path or self._path
        if not target:
            raise ValueError("No registry path configured")

        data = {
            "article_to_page": self._article_to_page,
            "section_pages": self._section_pages,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w") as f:
            json.dump(data, f, indent=2)
        logger.debug("Saved registry with %d mappings to %s", self.count, target)

    def load(self, path: Path | None = None) -> None:
        target = path or self._path
        if not target or not target.exists():
            return

        with open(target) as f:
            data = json.load(f)

        self._article_to_page = data.get("article_to_page", {})
        self._page_to_article = {v: k for k, v in self._article_to_page.items()}
        self._section_pages = data.get("section_pages", {})
        logger.debug("Loaded registry with %d mappings from %s", self.count, target)
