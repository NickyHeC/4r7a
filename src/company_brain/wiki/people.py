"""Company wiki ``people/`` directory stubs linking to employee wikis."""

from __future__ import annotations

from company_brain.wiki.employee_paths import member_prefix, people_page_path
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore, WikiStore


def ensure_people_stub(
    member_key: str,
    *,
    email: str = "",
    title: str | None = None,
    store: WikiStore | None = None,
    sync_notion: bool = True,
) -> str:
    """Create or update ``wiki/people/{member}.md`` with a link to the employee wiki."""
    store = store or LocalWikiStore()
    rel = people_page_path(member_key)
    display = title or member_key.replace("-", " ").title()
    employee_root = member_prefix(member_key).rstrip("/")

    body_lines = [
        f"# {display}",
        "",
        f"- **Member key:** `{member_key}`",
    ]
    if email:
        body_lines.append(f"- **Email:** {email}")
    body_lines.extend(
        [
            "",
            "## Employee wiki",
            "",
            "Work record and knowledge live in the employee wiki building:",
            f"`employee_wiki/{employee_root}/` (see `_index.md` for current work).",
            "",
            "_This page is the company directory entry; the employee wiki holds the work record._",
            "",
        ]
    )

    write_wiki_page(
        rel,
        display,
        "\n".join(body_lines),
        mode=UPDATE,
        section="people",
        type_="person",
        store=store,
        sync=sync_notion,
    )
    return rel
