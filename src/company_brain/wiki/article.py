"""Article data model for company wiki entries."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _make_slug(title: str) -> str:
    """Convert a title into a URL-safe slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug.strip("-")


class Article(BaseModel):
    """A single wiki article, either local-only or published to Notion."""

    id: str = ""
    title: str
    type: str
    section: str
    notion_page_id: str | None = None
    created: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    related: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            self.id = _make_slug(self.title)

    @property
    def is_published(self) -> bool:
        return self.notion_page_id is not None

    @property
    def is_stub(self) -> bool:
        """Articles with fewer than 15 content lines are stubs."""
        return len(self.content.strip().splitlines()) < 15

    def touch(self) -> None:
        """Update the last_updated timestamp."""
        self.last_updated = datetime.now(timezone.utc)

    def add_source(self, source_id: str) -> None:
        if source_id not in self.sources:
            self.sources.append(source_id)

    def add_related(self, article_id: str) -> None:
        if article_id != self.id and article_id not in self.related:
            self.related.append(article_id)
