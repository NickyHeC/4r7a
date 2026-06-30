"""Content Catalog Agent — regenerate ``admin/content-catalog.md``.

SDK: Neither (deterministic catalog walker + wiki write).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.external_wiki.external_wiki_config import catalog_config
from company_brain.config import AppConfig
from company_brain.wiki.content_catalog import (
    build_content_catalog,
    catalog_wiki_path,
    render_catalog_markdown,
)
from company_brain.wiki.publish import UPDATE, write_wiki_page


class ContentCatalogAgent(BaseAgent):
    """Rebuild the admin content table of contents."""

    name = "content_catalog"
    WRITE_MODE = UPDATE

    def run(self, **kwargs: Any) -> dict[str, Any]:
        cfg = catalog_config()
        catalog = build_content_catalog(include_employee_wiki=cfg.include_employee_wiki)
        body = render_catalog_markdown(catalog)
        rel_path = catalog_wiki_path()
        write_wiki_page(
            rel_path,
            "Content Catalog",
            body,
            mode=UPDATE,
            section="admin",
            sync_label="admin_only",
        )
        return {
            "status": "ok",
            "path": rel_path,
            "company_pages": catalog.company_page_count,
            "external_pages": catalog.external_page_count,
            "employee_buildings": len(catalog.employee_buildings),
        }
