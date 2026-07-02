"""Article data model for company wiki entries."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from company_brain.wiki.store import MarkdownDoc


def _make_slug(title: str) -> str:
    """Convert a title into a URL-safe slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug.strip("-")


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class Article(BaseModel):
    """A single wiki article, persisted as a Markdown file and mirrored to Notion."""

    id: str = ""
    title: str
    type: str = "page"
    section: str = ""
    notion_page_id: str | None = None
    created: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_synced: datetime | None = None
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

    def rel_path(self) -> str:
        """Path of this article's Markdown file inside the wiki store."""
        section = (self.section or "").strip("/")
        return f"{section}/{self.id}.md" if section else f"{self.id}.md"

    def touch(self) -> None:
        """Update the last_updated timestamp."""
        self.last_updated = datetime.now(timezone.utc)

    def add_source(self, source_id: str) -> None:
        if source_id not in self.sources:
            self.sources.append(source_id)

    def add_related(self, article_id: str) -> None:
        if article_id != self.id and article_id not in self.related:
            self.related.append(article_id)

    # -- Markdown doc conversion ---------------------------------------------

    def to_doc(self) -> "MarkdownDoc":
        """Render this article as a MarkdownDoc (frontmatter + body)."""
        from company_brain.wiki.store import MarkdownDoc

        fm: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "type": self.type,
            "section": self.section,
            "notion_page_id": self.notion_page_id,
            "related": self.related,
            "sources": self.sources,
            "created": _to_iso(self.created),
            "last_updated": _to_iso(self.last_updated),
            "last_synced": _to_iso(self.last_synced),
        }
        if self.metadata:
            fm["metadata"] = self.metadata
        return MarkdownDoc(frontmatter=fm, body=self.content)

    @classmethod
    def from_doc(cls, doc: "MarkdownDoc", rel_path: str | None = None) -> "Article":
        """Build an Article from a MarkdownDoc, tolerating sparse frontmatter."""
        fm = dict(doc.frontmatter or {})
        section = fm.get("section") or ""
        if not section and rel_path and "/" in rel_path:
            section = rel_path.rsplit("/", 1)[0]
        title = (
            fm.get("title")
            or _title_from_body(doc.body)
            or (rel_path.rsplit("/", 1)[-1].removesuffix(".md") if rel_path else "Untitled")
        )
        return cls(
            id=fm.get("id") or "",
            title=title,
            type=fm.get("type") or "page",
            section=section,
            notion_page_id=fm.get("notion_page_id"),
            created=fm.get("created") or datetime.now(timezone.utc),
            last_updated=fm.get("last_updated") or datetime.now(timezone.utc),
            last_synced=fm.get("last_synced"),
            related=fm.get("related") or [],
            sources=fm.get("sources") or [],
            content=doc.body,
            metadata=fm.get("metadata") or {},
        )


def _title_from_body(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None
