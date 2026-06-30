"""Bootstrap a member: people stub + employee wiki index page."""

from __future__ import annotations

from company_brain.wiki.employee_paths import member_index_path
from company_brain.wiki.employee_publish import UPDATE, write_employee_wiki_page
from company_brain.wiki.people import ensure_people_stub
from company_brain.wiki.store import WikiStore


def ensure_member_wiki(
    member_key: str,
    *,
    email: str = "",
    title: str | None = None,
    company_store: WikiStore | None = None,
    sync_notion: bool = False,
) -> dict[str, str]:
    """Create company ``people/`` stub and employee ``_index.md`` if missing."""
    people_rel = ensure_people_stub(
        member_key,
        email=email,
        title=title,
        store=company_store,
        sync_notion=sync_notion,
    )
    index_rel = member_index_path(member_key)
    write_employee_wiki_page(
        index_rel,
        "Current work",
        _default_index_body(member_key),
        member=member_key,
        mode=UPDATE,
        mirror_notion=sync_notion,
    )
    return {"people": people_rel, "index": index_rel}


def _default_index_body(member_key: str) -> str:
    return (
        f"# Current work — {member_key}\n\n"
        "_Ongoing projects and focus areas. Updated by platform materializers and imports._\n\n"
        "## Open projects\n\n_None yet._\n\n"
        "## This quarter\n\n_See work_log for detailed entries._\n"
    )
