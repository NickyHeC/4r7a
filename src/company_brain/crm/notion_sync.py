"""Mirror CRM contact and inbound wiki pages to Notion database rows.

MD remains source of truth; each ``crm/contact/{slug}.md`` and
``crm/inbound/{type}/{slug}.md`` syncs properties into the configured
``crm_databases`` entry. Skips when ``database_id`` is empty (Notion not
connected).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.operations.notion import db as notion_db
from company_brain.config import AppConfig, CrmDatabaseSpec, load_config
from company_brain.crm.config import INBOUND_TYPES, contact_dir, inbound_dir
from company_brain.notion.client import NotionClient
from company_brain.wiki.store import LocalWikiStore, WikiStore

logger = logging.getLogger(__name__)

INBOUND_TYPE_TO_DB: dict[str, str] = {
    "press-podcast": "inbound_press_podcast",
    "event-invitation": "inbound_event_invitation",
    "partnership": "inbound_partnership",
    "founder-networking": "inbound_founder_networking",
    "investor-interest": "inbound_investor_interest",
    "candidate": "inbound_candidate",
}


def configured_crm_database_keys(*, config: AppConfig | None = None) -> list[str]:
    config = config or load_config()
    return [key for key, spec in (config.notion.crm_databases or {}).items() if spec.database_id]


def crm_notion_available(
    *,
    config: AppConfig | None = None,
    client: NotionClient | None = None,
) -> bool:
    config = config or load_config()
    client = client or NotionClient()
    keys = configured_crm_database_keys(config=config)
    return notion_db.notion_is_available(client) and bool(keys)


def crm_database_key_for_rel_path(rel_path: str) -> str | None:
    """Return ``crm_databases`` config key for a wiki path, or None."""
    rel = rel_path.replace("\\", "/").lstrip("/")
    contact_prefix = contact_dir().rstrip("/") + "/"
    if rel.startswith(contact_prefix) and rel.endswith(".md"):
        stem = rel[len(contact_prefix) : -3]
        if stem and stem != "_index":
            return "crm_contacts"

    inbound_root = inbound_dir().rstrip("/") + "/"
    if not rel.startswith(inbound_root) or not rel.endswith(".md"):
        return None
    remainder = rel[len(inbound_root) :]
    parts = remainder.split("/", 1)
    if len(parts) != 2:
        return None
    inbound_type, filename = parts
    if inbound_type not in INBOUND_TYPES or inbound_type == "unmatched":
        return None
    if not filename.endswith(".md"):
        return None
    return INBOUND_TYPE_TO_DB.get(inbound_type)


def sync_crm_doc(
    rel_path: str,
    *,
    store: WikiStore | None = None,
    client: NotionClient | None = None,
    config: AppConfig | None = None,
    force: bool = False,
) -> str | None:
    """Sync one CRM contact or inbound page to its Notion database row."""
    config = config or load_config()
    db_key = crm_database_key_for_rel_path(rel_path)
    if not db_key:
        return None

    spec = (config.notion.crm_databases or {}).get(db_key)
    if not spec or not spec.database_id:
        logger.debug("CRM Notion skip (no database_id): %s -> %s", rel_path, db_key)
        return None

    client = client or NotionClient()
    if not notion_db.notion_is_available(client):
        logger.debug("CRM Notion skip (not available): %s", rel_path)
        return None

    store = store or LocalWikiStore()
    doc = store.read(rel_path)
    fm = dict(doc.frontmatter or {})
    page_id = str(fm.get("notion_page_id") or "")
    current_hash = doc.content_hash

    if page_id and not force and fm.get("synced_hash") == current_hash:
        logger.debug("CRM Notion skip (unchanged): %s", rel_path)
        return page_id

    values = _property_values(db_key, fm, spec)
    if not values.get(spec.columns.title):
        logger.warning("CRM Notion skip (missing title): %s", rel_path)
        return None

    if not page_id:
        page_id = _discover_row(client, spec.database_id, values, spec)

    if page_id:
        _patch_row(client, spec.database_id, page_id, values)
    else:
        page = _create_row(client, spec.database_id, values)
        page_id = str(page.get("id") or "")
        if not page_id:
            logger.warning("CRM Notion create failed: %s", rel_path)
            return None

    fm["notion_page_id"] = page_id
    fm["synced_hash"] = current_hash
    fm["last_synced"] = datetime.now(timezone.utc).isoformat()
    doc.frontmatter = fm
    store.write(rel_path, doc)
    logger.info("CRM synced %s -> Notion %s (%s)", rel_path, page_id, db_key)
    return page_id


def sync_all_crm(
    *,
    store: WikiStore | None = None,
    config: AppConfig | None = None,
) -> dict[str, str]:
    """Sync every CRM contact and inbound page that has a database binding."""
    store = store or LocalWikiStore()
    results: dict[str, str] = {}
    for rel_path in store.list():
        if not crm_database_key_for_rel_path(rel_path):
            continue
        try:
            page_id = sync_crm_doc(rel_path, store=store, config=config)
            if page_id:
                results[rel_path] = page_id
        except Exception:
            logger.exception("CRM Notion sync failed for %s", rel_path)
    return results


def _property_values(db_key: str, fm: dict[str, Any], spec: CrmDatabaseSpec) -> dict[str, str]:
    cols = spec.columns
    if db_key == "crm_contacts":
        return {
            cols.title: str(fm.get("title") or ""),
            cols.segment: str(fm.get("segment") or ""),
            cols.email: str(fm.get("canonical_email") or ""),
            cols.main_connection: str(fm.get("main_connection_employee") or ""),
            cols.status: str(fm.get("status") or "active"),
        }
    score = fm.get("score")
    received = str(fm.get("received_at") or fm.get("triaged_at") or "")
    return {
        cols.title: str(fm.get("title") or ""),
        cols.contact: str(fm.get("contact_slug") or ""),
        cols.score: str(score if score is not None else ""),
        cols.status: str(fm.get("status") or "open"),
        cols.received: received,
    }


def _build_properties(values: dict[str, str], *, schema: dict[str, str]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for prop_name, value in values.items():
        if not prop_name:
            continue
        ptype = schema.get(prop_name, "rich_text")
        if value == "" and ptype != "title":
            continue
        properties.update(notion_db.build_property_patch(prop_name, value, schema=schema))
    return properties


def _create_row(
    client: NotionClient,
    database_id: str,
    values: dict[str, str],
) -> dict[str, Any]:
    schema = notion_db.get_database_schema(client, database_id)
    properties = _build_properties(values, schema=schema)
    result = client.api(
        "v1/pages",
        method="POST",
        data=json.dumps({"parent": {"database_id": database_id}, "properties": properties}),
    )
    if result.json_data and isinstance(result.json_data, dict):
        return result.json_data
    return {}


def _patch_row(
    client: NotionClient,
    database_id: str,
    page_id: str,
    values: dict[str, str],
) -> dict[str, Any]:
    schema = notion_db.get_database_schema(client, database_id)
    properties = _build_properties(values, schema=schema)
    if not properties:
        return {}
    result = client.api(
        f"v1/pages/{page_id}",
        method="PATCH",
        data=json.dumps({"properties": properties}),
    )
    if result.json_data and isinstance(result.json_data, dict):
        return result.json_data
    return {}


def _discover_row(
    client: NotionClient,
    database_id: str,
    values: dict[str, str],
    spec: CrmDatabaseSpec,
) -> str:
    title_col = spec.columns.title
    title = values.get(title_col, "").strip()
    if not title:
        return ""
    body = {
        "page_size": 5,
        "filter": {
            "property": title_col,
            "title": {"equals": title},
        },
    }
    result = client.api(
        f"v1/databases/{database_id}/query",
        method="POST",
        data=json.dumps(body),
    )
    if not result.json_data or not isinstance(result.json_data, dict):
        return ""
    rows = result.json_data.get("results") or []
    if rows:
        return str(rows[0].get("id") or "")
    return ""
