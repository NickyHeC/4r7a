"""Raw entry model: a unit of ingested information before absorption."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from company_brain.wiki.store import MarkdownDoc


class RawEntry(BaseModel):
    """A single unit of information from any source.

    Raw entries are the input to the absorption process. They get matched
    against existing articles, and their content is woven into new or
    updated wiki articles.
    """

    id: str = ""
    source_type: str
    source_id: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    title: str = ""
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    absorbed: bool = False
    absorbed_into: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            digest = hashlib.sha256(
                f"{self.source_type}:{self.source_id}:{self.content[:200]}".encode()
            ).hexdigest()[:12]
            self.id = f"{self.source_type}-{digest}"

    def mark_absorbed(self, article_ids: list[str]) -> None:
        self.absorbed = True
        self.absorbed_into = list(set(self.absorbed_into + article_ids))

    # -- Markdown doc conversion ---------------------------------------------

    def filename(self) -> str:
        return f"{self.timestamp.strftime('%Y-%m-%d')}_{self.id}.md"

    def to_doc(self) -> "MarkdownDoc":
        from company_brain.wiki.store import MarkdownDoc

        fm: dict[str, Any] = {
            "id": self.id,
            "date": self.timestamp.strftime("%Y-%m-%d"),
            "timestamp": self.timestamp.isoformat(),
            "source_type": self.source_type,
            "source_id": self.source_id,
            "title": self.title,
            "tags": self.tags,
            "absorbed": self.absorbed,
            "absorbed_into": self.absorbed_into,
        }
        if self.metadata:
            fm["metadata"] = self.metadata
        return MarkdownDoc(frontmatter=fm, body=self.content)

    @classmethod
    def from_doc(cls, doc: "MarkdownDoc") -> "RawEntry":
        fm = dict(doc.frontmatter or {})
        return cls(
            id=fm.get("id") or "",
            source_type=fm.get("source_type") or "unknown",
            source_id=fm.get("source_id") or "",
            timestamp=fm.get("timestamp") or fm.get("date") or datetime.now(timezone.utc),
            title=fm.get("title") or "",
            content=doc.body,
            metadata=fm.get("metadata") or {},
            tags=fm.get("tags") or [],
            absorbed=bool(fm.get("absorbed", False)),
            absorbed_into=fm.get("absorbed_into") or [],
        )
