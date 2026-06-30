"""Employee Wiki Onboarding — bootstrap member wiki + Notion personal teamspace.

Runs once per member: creates company ``people/`` stub, employee ``_index.md``,
discovers-or-creates the member's Notion teamspace parent, and syncs the index page.

SDK: Neither (orchestration + Notion via ``member_teamspace`` helper).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.config import AppConfig
from company_brain.members_config import load_members_config
from company_brain.notion.client import NotionClient
from company_brain.notion.member_teamspace import ensure_member_teamspace_parent, member_teamspace_key
from company_brain.wiki.employee_notion_sync import sync_employee_doc
from company_brain.wiki.member_bootstrap import ensure_member_wiki


class EmployeeWikiOnboardingAgent(BaseAgent):
    """One-time onboarding for a member's employee wiki building."""

    name = "employee_wiki_onboarding"

    def run(
        self,
        *,
        member_key: str,
        email: str = "",
        title: str | None = None,
        mirror_notion: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        key = (member_key or "").strip()
        if not key:
            return {"status": "error", "reason": "member_key required"}

        members = load_members_config()
        if key not in members.members:
            self.logger.warning("Member %s not in config/members.yaml — continuing anyway", key)

        paths = ensure_member_wiki(
            key,
            email=email or (members.get(key).email if members.get(key) else ""),
            title=title,
            sync_notion=False,
        )

        notion_parent: str | None = None
        synced_page: str | None = None
        if mirror_notion and NotionClient().check_auth():
            notion_parent = ensure_member_teamspace_parent(key, create=True)
            if notion_parent:
                synced_page = sync_employee_doc(paths["index"])

        return {
            "status": "ok",
            "member": key,
            "people_page": paths["people"],
            "index_page": paths["index"],
            "notion_teamspace_key": member_teamspace_key(key),
            "notion_parent_id": notion_parent,
            "notion_page_id": synced_page,
        }
