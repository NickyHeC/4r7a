"""Conflict resolution helpers — evidence scoring + Notion DB mirror."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from company_brain.agents.operations.notion import db
from company_brain.config import load_config
from company_brain.notion.client import NotionClient
from company_brain.notion.scoped_search import search_scoped_snippets
from company_brain.wiki.store import WikiStore

logger = logging.getLogger(__name__)

WIKI_PATH = "operations/notion/conflict-resolution.md"
TITLE = "Conflict Resolutions"

STATUS_OPEN = "open"
STATUS_RESOLVED_MD = "resolved_md"
STATUS_RESOLVED_NOTION = "resolved_notion"
STATUS_APPLIED = "applied"


def conflict_db_cfg() -> dict[str, Any]:
    return dict(load_config().notion.conflict_resolution_database or {})


def database_id() -> str:
    return str(conflict_db_cfg().get("database_id") or "").strip()


def columns() -> dict[str, str]:
    raw = conflict_db_cfg().get("columns") or {}
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def notion_db_available(client: NotionClient | None = None) -> bool:
    client = client or NotionClient()
    return db.notion_is_available(client) and bool(database_id())


def significant_terms(text: str, *, min_len: int = 4) -> set[str]:
    return {t for t in re.split(r"\W+", (text or "").lower()) if len(t) >= min_len}


def score_side(body: str, snippets: list[dict[str, Any]]) -> int:
    terms = significant_terms(body)
    if not terms:
        return 0
    score = 0
    for snip in snippets:
        blob = f"{snip.get('title', '')}\n{snip.get('snippet', '')}".lower()
        score += sum(1 for t in terms if t in blob)
    return score


def evidence_winner(
    md_body: str,
    notion_body: str,
    snippets: list[dict[str, Any]],
    *,
    margin: int = 3,
    min_hits: int = 4,
) -> str | None:
    """Return ``md`` / ``notion`` when evidence clearly favors one side; else None."""
    if len(snippets) < 2:
        return None
    md_score = score_side(md_body, snippets)
    notion_score = score_side(notion_body, snippets)
    if md_score < min_hits and notion_score < min_hits:
        return None
    if md_score >= notion_score + margin and md_score >= min_hits:
        return "md"
    if notion_score >= md_score + margin and notion_score >= min_hits:
        return "notion"
    return None


def gather_conflict_evidence(
    *,
    store: WikiStore,
    md_body: str,
    notion_body: str,
    prefixes: list[str],
    exclude: str | None = None,
) -> list[dict[str, Any]]:
    query = " ".join(sorted(significant_terms(md_body) | significant_terms(notion_body))[:12])
    return search_scoped_snippets(
        query,
        store=store,
        prefixes=prefixes,
        limit=8,
        exclude=exclude,
    )


def create_conflict_row(
    *,
    title: str,
    rel_path: str,
    reason: str,
    client: NotionClient | None = None,
) -> str:
    db_id = database_id()
    if not db_id:
        return ""
    client = client or NotionClient()
    if not db.notion_is_available(client):
        return ""
    cols = columns()
    schema = db.get_database_schema(client, db_id)
    properties: dict[str, Any] = {}
    properties.update(db.build_property_patch(cols.get("title", "Title"), title, schema=schema))
    properties.update(
        db.build_property_patch(cols.get("status", "Status"), STATUS_OPEN, schema=schema)
    )
    properties.update(
        db.build_property_patch(cols.get("rel_path", "Path"), rel_path, schema=schema)
    )
    properties.update(
        db.build_property_patch(cols.get("reason", "Reason"), reason[:1900], schema=schema)
    )
    result = client.api(
        "v1/pages",
        method="POST",
        data=json.dumps({"parent": {"database_id": db_id}, "properties": properties}),
    )
    if result.json_data and isinstance(result.json_data, dict):
        return str(result.json_data.get("id") or "")
    logger.warning("Conflict resolution Notion row create returned no id")
    return ""


def query_resolved_rows(client: NotionClient | None = None) -> list[dict[str, Any]]:
    """Return conflict DB rows awaiting apply (resolved_md / resolved_notion)."""
    db_id = database_id()
    if not db_id:
        return []
    client = client or NotionClient()
    if not db.notion_is_available(client):
        return []
    cols = columns()
    status_col = cols.get("status", "Status")
    rows: list[dict[str, Any]] = []
    for status in (STATUS_RESOLVED_MD, STATUS_RESOLVED_NOTION):
        body = {
            "page_size": 50,
            "filter": {"property": status_col, "status": {"equals": status}},
        }
        # status property may be select — try status first, fall back to select via raw query
        result = client.api(
            f"v1/databases/{db_id}/query",
            method="POST",
            data=json.dumps(body),
        )
        if result.returncode != 0:
            body["filter"] = {"property": status_col, "select": {"equals": status}}
            result = client.api(
                f"v1/databases/{db_id}/query",
                method="POST",
                data=json.dumps(body),
            )
        if result.json_data and isinstance(result.json_data, dict):
            rows.extend(result.json_data.get("results") or [])
    return rows


def read_conflict_fields(page: dict[str, Any]) -> dict[str, str]:
    cols = columns()
    props = page.get("properties") or {}
    return {
        "title": db.extract_property_text(props.get(cols.get("title", "Title"))),
        "status": db.extract_property_text(props.get(cols.get("status", "Status"))),
        "rel_path": db.extract_property_text(props.get(cols.get("rel_path", "Path"))),
        "reason": db.extract_property_text(props.get(cols.get("reason", "Reason"))),
        "winner": db.extract_property_text(props.get(cols.get("winner", "Winner"))),
    }


def mark_row_applied(page_id: str, client: NotionClient | None = None) -> None:
    if not page_id:
        return
    client = client or NotionClient()
    cols = columns()
    schema = db.get_database_schema(client, database_id())
    properties = db.build_property_patch(
        cols.get("status", "Status"),
        STATUS_APPLIED,
        schema=schema,
    )
    client.api(
        f"v1/pages/{page_id}",
        method="PATCH",
        data=json.dumps({"properties": properties}),
    )
