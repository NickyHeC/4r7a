"""CRM wiki seeds — indexes, promotion log, inbound directories."""

from __future__ import annotations

from company_brain.config import resolve_wiki_dir
from company_brain.crm.config import (
    INBOUND_TYPES,
    customer_index_path,
    investor_index_path,
    promotion_log_path,
)
from company_brain.crm.schema import default_index_body
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore


def ensure_crm_seeds(*, wiki_root=None) -> int:
    """Create empty CRM structure if missing. Returns count of pages created."""
    root = wiki_root or resolve_wiki_dir()
    store = LocalWikiStore(root=root)
    created = 0

    seeds: list[tuple[str, str, str]] = [
        (
            customer_index_path(),
            "Customers",
            default_index_body("Customers", list_heading="Confirmed customers"),
        ),
        (
            investor_index_path(),
            "Investors",
            default_index_body("Investors", list_heading="Confirmed investors"),
        ),
        (
            promotion_log_path(),
            "CRM Promotion Log",
            "# CRM Promotion Log\n\nAppend-only audit of segment promotions.\n",
        ),
    ]

    for rel_path, title, body in seeds:
        if store.exists(rel_path):
            continue
        write_wiki_page(rel_path, title, body, mode=UPDATE, section="crm", sync=False)
        created += 1

    for inbound_type in INBOUND_TYPES:
        marker = f"crm/inbound/{inbound_type}/.gitkeep"
        path = store.abspath(marker)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
            created += 1

    return created
