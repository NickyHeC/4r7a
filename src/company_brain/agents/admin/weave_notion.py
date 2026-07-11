"""Notion mirror for Weave change requests."""

from __future__ import annotations

import json
import logging
from typing import Any

from company_brain.agents.admin.change_request import ChangeRequest
from company_brain.agents.operations.notion import db
from company_brain.config import load_config
from company_brain.notion.client import NotionClient

logger = logging.getLogger(__name__)


def weave_notion_cfg() -> dict[str, Any]:
    return dict(load_config().notion.change_request_database or {})


def database_id() -> str:
    return str(weave_notion_cfg().get("database_id") or "").strip()


def columns() -> dict[str, str]:
    raw = weave_notion_cfg().get("columns") or {}
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def notion_available() -> bool:
    client = NotionClient()
    return db.notion_is_available(client) and bool(database_id())


def create_change_request_row(req: ChangeRequest) -> str:
    """Create a Notion database row; returns page id or ''."""
    db_id = database_id()
    if not db_id:
        return ""
    client = NotionClient()
    if not db.notion_is_available(client):
        return ""

    cols = columns()
    schema = db.get_database_schema(client, db_id)
    properties: dict[str, Any] = {}
    title_col = cols.get("title", "Title")
    status_col = cols.get("status", "Status")
    requester_col = cols.get("requester", "Requester")
    class_col = cols.get("change_class", "Class")
    thread_col = cols.get("slack_thread", "Slack thread")
    pr_col = cols.get("pr_url", "PR")

    properties.update(db.build_property_patch(title_col, req.title, schema=schema))
    properties.update(db.build_property_patch(status_col, req.status, schema=schema))
    properties.update(db.build_property_patch(requester_col, req.requester_member, schema=schema))
    properties.update(db.build_property_patch(class_col, req.change_class, schema=schema))
    if req.slack_permalink:
        properties.update(db.build_property_patch(thread_col, req.slack_permalink, schema=schema))
    if req.pr_url:
        properties.update(db.build_property_patch(pr_col, req.pr_url, schema=schema))

    result = client.api(
        "v1/pages",
        method="POST",
        data=json.dumps({"parent": {"database_id": db_id}, "properties": properties}),
    )
    if result.json_data and isinstance(result.json_data, dict):
        return str(result.json_data.get("id") or "")
    logger.warning("Notion change-request row create returned no id")
    return ""


def update_change_request_row(
    page_id: str,
    *,
    status: str | None = None,
    pr_url: str | None = None,
) -> None:
    if not page_id:
        return
    db_id = database_id()
    if not db_id:
        return
    client = NotionClient()
    if not db.notion_is_available(client):
        return

    cols = columns()
    schema = db.get_database_schema(client, db_id)
    properties: dict[str, Any] = {}
    if status:
        properties.update(
            db.build_property_patch(cols.get("status", "Status"), status, schema=schema)
        )
    if pr_url:
        properties.update(db.build_property_patch(cols.get("pr_url", "PR"), pr_url, schema=schema))
    if not properties:
        return
    client.api(
        f"v1/pages/{page_id}",
        method="PATCH",
        data=json.dumps({"properties": properties}),
    )


def list_approved_requests() -> list[dict[str, str]]:
    """Return approved change requests from Notion (id, title, status)."""
    db_id = database_id()
    if not db_id:
        return []
    client = NotionClient()
    if not db.notion_is_available(client):
        return []

    cols = columns()
    status_col = cols.get("status", "Status")
    rows = db.query_database_updated_since(
        client,
        db_id,
        "1970-01-01T00:00:00.000Z",
        page_size=100,
    )
    approved: list[dict[str, str]] = []
    for row in rows:
        props = row.get("properties") or {}
        status = db.extract_property_text(props.get(status_col))
        if status.strip().lower() != "approved":
            continue
        title = db.extract_property_text(props.get(cols.get("title", "Title")))
        approved.append(
            {
                "notion_page_id": str(row.get("id") or ""),
                "title": title,
                "url": db.page_url(row),
            }
        )
    return approved
