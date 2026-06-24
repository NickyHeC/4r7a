"""Granola REST API client (read-only).

Docs: https://docs.granola.ai/introduction
API base: https://public-api.granola.ai
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

from company_brain.agents.operations.shared import granola_config as cfg

API_BASE = "https://public-api.granola.ai"
DEFAULT_PAGE_SIZE = 30


class GranolaAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _request(
    method: str,
    path: str,
    *,
    api_key: str,
    params: dict[str, Any] | None = None,
) -> Any:
    url = f"{API_BASE}{path}"
    response = requests.request(
        method,
        url,
        headers=_headers(api_key),
        params=params,
        timeout=60,
    )
    if response.status_code == 401:
        raise GranolaAPIError("Invalid Granola API key", status_code=401)
    if response.status_code == 404:
        raise GranolaAPIError("Granola resource not found", status_code=404)
    if not response.ok:
        raise GranolaAPIError(
            f"Granola API error {response.status_code}: {response.text[:200]}",
            status_code=response.status_code,
        )
    return response.json()


def list_notes(
    api_key: str,
    *,
    created_after: date | datetime | None = None,
    created_before: date | datetime | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> list[dict[str, Any]]:
    """List all notes in range, following pagination cursors."""
    params: dict[str, Any] = {"page_size": page_size}
    if created_after is not None:
        params["created_after"] = _format_filter_ts(created_after)
    if created_before is not None:
        params["created_before"] = _format_filter_ts(created_before)

    notes: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page_params = dict(params)
        if cursor:
            page_params["cursor"] = cursor
        payload = _request("GET", "/v1/notes", api_key=api_key, params=page_params)
        notes.extend(payload.get("notes") or [])
        if not payload.get("hasMore"):
            break
        cursor = payload.get("cursor")
        if not cursor:
            break
    return notes


def get_note(api_key: str, note_id: str, *, include_transcript: bool = True) -> dict[str, Any]:
    params = {"include": "transcript"} if include_transcript else None
    return _request("GET", f"/v1/notes/{note_id}", api_key=api_key, params=params)


def list_notes_for_day(api_key: str, day: date) -> list[dict[str, Any]]:
    """Notes whose ``created_at`` falls on ``day`` (UTC day window)."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return list_notes(api_key, created_after=start, created_before=end)


def check_connection(api_key: str | None = None) -> bool:
    """Cheap auth check — list one note page."""
    key = api_key or cfg.enterprise_api_key()
    if not key:
        keys = cfg.member_api_keys()
        if not keys:
            return False
        key = keys[0][2]
    try:
        _request("GET", "/v1/notes", api_key=key, params={"page_size": 1})
        return True
    except GranolaAPIError:
        return False


def _format_filter_ts(value: date | datetime) -> str:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
