"""Notion database helpers — query, extract, and patch task row properties."""

from __future__ import annotations

import json
import logging
from typing import Any

from company_brain.config import TaskDatabaseSpec
from company_brain.notion.client import NotionClient

logger = logging.getLogger(__name__)

_SCHEMA_CACHE: dict[str, dict[str, str]] = {}


def notion_is_available(client: NotionClient | None = None) -> bool:
    client = client or NotionClient()
    return client.is_installed() and client.check_auth()


def page_url(page: dict[str, Any]) -> str:
    url = page.get("url") or ""
    if url:
        return str(url)
    page_id = str(page.get("id") or "").replace("-", "")
    if page_id:
        return f"https://www.notion.so/{page_id}"
    return ""


def extract_property_text(prop: dict[str, Any] | None) -> str:
    if not prop or not isinstance(prop, dict):
        return ""
    ptype = prop.get("type")
    if ptype == "title":
        return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    if ptype == "rich_text":
        return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
    if ptype == "status":
        status = prop.get("status") or {}
        return str(status.get("name") or "")
    if ptype == "select":
        sel = prop.get("select") or {}
        return str(sel.get("name") or "")
    return ""


def read_row_fields(page: dict[str, Any], spec: TaskDatabaseSpec) -> dict[str, str]:
    props = page.get("properties") or {}
    cols = spec.columns
    return {
        "title": extract_property_text(props.get(cols.title)),
        "status": extract_property_text(props.get(cols.status)),
        "linear": extract_property_text(props.get(cols.linear)),
    }


def get_database_schema(
    client: NotionClient,
    database_id: str,
    *,
    refresh: bool = False,
) -> dict[str, str]:
    """Map property name -> Notion property type."""
    if not refresh and database_id in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[database_id]
    result = client.api(f"v1/databases/{database_id}")
    schema: dict[str, str] = {}
    if result.json_data and isinstance(result.json_data, dict):
        for name, prop in (result.json_data.get("properties") or {}).items():
            if isinstance(prop, dict):
                schema[name] = str(prop.get("type") or "")
    _SCHEMA_CACHE[database_id] = schema
    return schema


def query_database_updated_since(
    client: NotionClient,
    database_id: str,
    since_iso: str,
    *,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """Return database rows edited after ``since_iso`` (UTC ISO-8601)."""
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    body: dict[str, Any] = {
        "page_size": page_size,
        "filter": {
            "timestamp": "last_edited_time",
            "last_edited_time": {"after": since_iso},
        },
    }
    while True:
        payload = dict(body)
        if cursor:
            payload["start_cursor"] = cursor
        result = client.api(
            f"v1/databases/{database_id}/query",
            method="POST",
            data=json.dumps(payload),
        )
        if not result.json_data or not isinstance(result.json_data, dict):
            break
        rows.extend(result.json_data.get("results") or [])
        if not result.json_data.get("has_more"):
            break
        cursor = result.json_data.get("next_cursor")
    return rows


def build_property_patch(
    property_name: str,
    value: str,
    *,
    schema: dict[str, str],
) -> dict[str, Any]:
    ptype = schema.get(property_name, "rich_text")
    if ptype == "title":
        return {property_name: {"title": [{"text": {"content": value}}]}}
    if ptype == "status":
        return {property_name: {"status": {"name": value}}}
    if ptype == "select":
        return {property_name: {"select": {"name": value}}}
    return {property_name: {"rich_text": [{"text": {"content": value}}]}}


def create_database_row(
    client: NotionClient,
    database_id: str,
    *,
    spec: TaskDatabaseSpec,
    title: str,
    linear_identifier: str = "",
    status: str = "",
) -> dict[str, Any]:
    schema = get_database_schema(client, database_id)
    properties: dict[str, Any] = {}
    properties.update(
        build_property_patch(spec.columns.title, title, schema=schema),
    )
    if linear_identifier:
        properties.update(
            build_property_patch(spec.columns.linear, linear_identifier, schema=schema),
        )
    if status and spec.columns.status:
        properties.update(
            build_property_patch(spec.columns.status, status, schema=schema),
        )
    result = client.api(
        "v1/pages",
        method="POST",
        data=json.dumps({
            "parent": {"database_id": database_id},
            "properties": properties,
        }),
    )
    if result.json_data and isinstance(result.json_data, dict):
        return result.json_data
    logger.warning("Notion create row returned no JSON for database %s", database_id)
    return {}


def update_database_row(
    client: NotionClient,
    page_id: str,
    *,
    spec: TaskDatabaseSpec,
    database_id: str,
    title: str | None = None,
    status: str | None = None,
    linear_identifier: str | None = None,
) -> dict[str, Any]:
    schema = get_database_schema(client, database_id)
    properties: dict[str, Any] = {}
    if title is not None:
        properties.update(
            build_property_patch(spec.columns.title, title, schema=schema),
        )
    if status is not None and spec.columns.status:
        properties.update(
            build_property_patch(spec.columns.status, status, schema=schema),
        )
    if linear_identifier is not None and spec.columns.linear:
        properties.update(
            build_property_patch(spec.columns.linear, linear_identifier, schema=schema),
        )
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
