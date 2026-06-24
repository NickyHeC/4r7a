"""Google Calendar REST client for deterministic gcal agents.

Uses ``GCAL_OAUTH_ACCESS_TOKEN`` or ``GMAIL_OAUTH_ACCESS_TOKEN``.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from company_brain.agents.operations.shared.gcal_config import (
    calendar_id,
    oauth_access_token,
    timezone_name,
)

API_BASE = "https://www.googleapis.com/calendar/v3"


class GCalAPIError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"Calendar API {status}: {detail[:400]}")
        self.status = status


def _token() -> str:
    tok = oauth_access_token()
    if not tok:
        raise RuntimeError(
            "GCAL_OAUTH_ACCESS_TOKEN or GMAIL_OAUTH_ACCESS_TOKEN not set — see project_install.md"
        )
    return tok


def _request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
) -> Any:
    url = f"{API_BASE}/{path.lstrip('/')}"
    resp = requests.request(
        method,
        url,
        headers={"Authorization": f"Bearer {_token()}"},
        params=params,
        json=json_body,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise GCalAPIError(resp.status_code, resp.text)
    if resp.status_code == 204 or not resp.content:
        return {}
    return resp.json()


def list_calendars() -> list[dict[str, Any]]:
    data = _request("GET", "/users/me/calendarList")
    return data.get("items") or []


def free_busy(
    time_min: datetime,
    time_max: datetime,
    *,
    calendars: list[str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    body = {
        "timeMin": _to_rfc3339(time_min),
        "timeMax": _to_rfc3339(time_max),
        "items": [{"id": cid} for cid in (calendars or [calendar_id()])],
    }
    data = _request("POST", "/freeBusy", json_body=body)
    cal = data.get("calendars") or {}
    cid = calendar_id()
    return {k: v.get("busy") or [] for k, v in cal.items() if k == cid or not calendars}


def list_events(
    time_min: datetime,
    time_max: datetime,
    *,
    cal_id: str | None = None,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    params = {
        "timeMin": _to_rfc3339(time_min),
        "timeMax": _to_rfc3339(time_max),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": max_results,
    }
    data = _request("GET", f"/calendars/{cal_id or calendar_id()}/events", params=params)
    return data.get("items") or []


def get_event(event_id: str, *, cal_id: str | None = None) -> dict[str, Any]:
    return _request("GET", f"/calendars/{cal_id or calendar_id()}/events/{event_id}")


def create_event(
    *,
    summary: str,
    start: datetime,
    end: datetime,
    description: str = "",
    attendee_emails: list[str] | None = None,
    with_meet: bool = True,
    cal_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "summary": summary,
        "description": description,
        "start": _event_time(start),
        "end": _event_time(end),
    }
    if attendee_emails:
        body["attendees"] = [{"email": email} for email in attendee_emails]
    if with_meet:
        body["conferenceData"] = {
            "createRequest": {
                "requestId": f"cb-{int(start.timestamp())}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
    params = {"conferenceDataVersion": 1} if with_meet else None
    return _request(
        "POST",
        f"/calendars/{cal_id or calendar_id()}/events",
        params=params,
        json_body=body,
    )


def check_connection() -> bool:
    try:
        list_calendars()
        return True
    except (GCalAPIError, RuntimeError):
        return False


def _to_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _event_time(dt: datetime) -> dict[str, str]:
    tz = ZoneInfo(timezone_name())
    local = dt.astimezone(tz) if dt.tzinfo else dt.replace(tzinfo=tz)
    return {"dateTime": local.isoformat(), "timeZone": timezone_name()}


def parse_event_bounds(event: dict[str, Any]) -> tuple[datetime, datetime] | None:
    start = event.get("start") or {}
    end = event.get("end") or {}
    start_raw = start.get("dateTime") or start.get("date")
    end_raw = end.get("dateTime") or end.get("date")
    if not start_raw or not end_raw:
        return None
    return _parse_dt(start_raw), _parse_dt(end_raw)


def _parse_dt(raw: str) -> datetime:
    if len(raw) == 10:
        return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
    cleaned = raw.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned)


def events_for_day(day: date, *, cal_id: str | None = None) -> list[dict[str, Any]]:
    tz = ZoneInfo(timezone_name())
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return list_events(start, end, cal_id=cal_id)
