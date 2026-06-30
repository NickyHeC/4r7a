"""Path helpers for employee wiki layouts."""

from __future__ import annotations

from datetime import date, datetime


def quarter_slug(value: date | datetime | None = None) -> str:
    """Return ``YYYY-QN`` for a date (calendar quarter)."""
    d = value.date() if isinstance(value, datetime) else (value or date.today())
    quarter = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{quarter}"


def member_prefix(member_key: str) -> str:
    key = (member_key or "").strip().strip("/")
    if not key:
        raise ValueError("member_key required")
    return f"{key}/"


def member_index_path(member_key: str) -> str:
    return f"{member_prefix(member_key)}_index.md"


def member_work_log_path(member_key: str, *, when: date | datetime | None = None) -> str:
    return f"{member_prefix(member_key)}work_log/{quarter_slug(when)}.md"


def member_project_path(member_key: str, project_slug: str) -> str:
    slug = _slug(project_slug)
    return f"{member_prefix(member_key)}projects/{slug}.md"


def member_quarantine_path(member_key: str, import_id: str) -> str:
    return f"{member_prefix(member_key)}imports/_quarantine/{import_id}/"


def people_page_path(member_key: str) -> str:
    """Company wiki people directory entry (not under employee wiki root)."""
    return f"people/{_slug(member_key)}.md"


def import_review_wiki_path(import_id: str) -> str:
    return f"engineering/admin/import-reviews/{import_id}.md"


def _slug(value: str) -> str:
    out = "".join(c if c.isalnum() or c in "-_" else "-" for c in value.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "general"
