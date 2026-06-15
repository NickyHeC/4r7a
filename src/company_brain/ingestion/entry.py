"""Raw entry model: a unit of ingested information before absorption."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


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
