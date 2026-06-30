"""Path helpers for external wiki mounts and admin pages."""

from __future__ import annotations

from company_brain.wiki.employee_paths import _slug


def source_slug(source_key: str) -> str:
    return _slug(source_key)


def external_quarantine_rel(source_key: str, import_id: str) -> str:
    key = source_slug(source_key)
    iid = (import_id or "").strip().strip("/")
    return f"external/_quarantine/{key}/{iid}/"


def external_promote_prefix(source_key: str) -> str:
    return f"external/{source_slug(source_key)}/"


def external_landing_path(source_key: str) -> str:
    return f"{external_promote_prefix(source_key)}_index.md"


def external_mount_review_path(import_id: str) -> str:
    iid = (import_id or "").strip().strip("/")
    return f"admin/external-mount-reviews/{iid}.md"


def import_review_wiki_path(import_id: str) -> str:
    """Employee zip import review page (top-level admin section)."""
    iid = (import_id or "").strip().strip("/")
    return f"admin/import-reviews/{iid}.md"


def admin_table_of_contents_path() -> str:
    return "admin/table-of-contents.md"
