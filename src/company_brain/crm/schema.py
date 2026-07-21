"""CRM entity schemas — contact and inbound frontmatter defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from company_brain.crm.config import SEGMENTS


@dataclass
class ContactEntity:
    slug: str
    title: str
    segment: str
    canonical_email: str = ""
    canonical_domain: str = ""
    aliases: list[str] = field(default_factory=list)
    main_connection_employee: str = ""
    status: str = "active"
    priority: int | None = None
    promoted_from: str = ""
    promoted_at: str = ""
    sources: list[str] = field(default_factory=list)
    body: str = ""

    def validate(self) -> None:
        if self.segment not in SEGMENTS:
            raise ValueError(f"invalid segment: {self.segment}")
        if self.segment == "connection" and not self.main_connection_employee:
            raise ValueError("connection segment requires main_connection_employee")
        if self.priority is not None and not (1 <= int(self.priority) <= 10):
            raise ValueError("priority must be 1–10 when set")

    def to_frontmatter(self) -> dict[str, Any]:
        fm: dict[str, Any] = {
            "title": self.title,
            "segment": self.segment,
            "status": self.status,
        }
        if self.canonical_email:
            fm["canonical_email"] = self.canonical_email
        if self.canonical_domain:
            fm["canonical_domain"] = self.canonical_domain
        if self.aliases:
            fm["aliases"] = list(self.aliases)
        if self.main_connection_employee:
            fm["main_connection_employee"] = self.main_connection_employee
        if self.priority is not None:
            fm["priority"] = int(self.priority)
        if self.promoted_from:
            fm["promoted_from"] = self.promoted_from
        if self.promoted_at:
            fm["promoted_at"] = self.promoted_at
        if self.sources:
            fm["sources"] = list(self.sources)
        return fm

    @classmethod
    def from_doc(cls, slug: str, frontmatter: dict[str, Any], body: str) -> "ContactEntity":
        aliases = frontmatter.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        sources = frontmatter.get("sources") or []
        if isinstance(sources, str):
            sources = [sources]
        raw_priority = frontmatter.get("priority")
        priority: int | None
        if raw_priority is None or raw_priority == "":
            priority = None
        else:
            priority = int(raw_priority)
        return cls(
            slug=slug,
            title=str(frontmatter.get("title") or slug),
            segment=str(frontmatter.get("segment") or "connection"),
            canonical_email=str(frontmatter.get("canonical_email") or "").lower(),
            canonical_domain=str(frontmatter.get("canonical_domain") or "").lower(),
            aliases=[str(a).lower() for a in aliases],
            main_connection_employee=str(frontmatter.get("main_connection_employee") or ""),
            status=str(frontmatter.get("status") or "active"),
            priority=priority,
            promoted_from=str(frontmatter.get("promoted_from") or ""),
            promoted_at=str(frontmatter.get("promoted_at") or ""),
            sources=[str(s) for s in sources],
            body=body,
        )


DEFAULT_CONTACT_BODY = """## Interactions

## Notes

"""


def default_index_body(title: str, *, list_heading: str) -> str:
    return f"# {title}\n\n{list_heading} (email or domain, one per line):\n\n"
