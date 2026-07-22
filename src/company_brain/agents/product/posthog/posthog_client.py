"""PostHog private REST client — READ ONLY.

Exposes GET list/detail helpers and POST ``/query`` for HogQL. Never PATCHes or
DELETEs PostHog resources. Mutating methods are intentionally absent.

Configuration (environment only — never hardcode secrets):
  - ``POSTHOG_PERSONAL_API_KEY``
  - ``POSTHOG_PROJECT_ID``
  - ``POSTHOG_HOST`` (optional; default ``https://us.posthog.com``)

Uses ``requests``. Tests mock ``_request`` / list helpers.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)

_ENV_KEYS = ("POSTHOG_PERSONAL_API_KEY", "POSTHOG_PROJECT_ID")
DEFAULT_HOST = "https://us.posthog.com"


class PostHogClientError(RuntimeError):
    pass


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def posthog_is_configured() -> bool:
    return all(_env(k) for k in _ENV_KEYS)


def host() -> str:
    return (_env("POSTHOG_HOST") or DEFAULT_HOST).rstrip("/")


def project_id() -> str:
    pid = _env("POSTHOG_PROJECT_ID")
    if not pid:
        raise PostHogClientError("POSTHOG_PROJECT_ID not set — see project_install.md")
    return pid


def personal_api_key() -> str:
    key = _env("POSTHOG_PERSONAL_API_KEY")
    if not key:
        raise PostHogClientError("POSTHOG_PERSONAL_API_KEY not set — see project_install.md")
    return key


@dataclass(frozen=True)
class FeatureFlag:
    id: int | str
    key: str
    name: str
    active: bool


@dataclass(frozen=True)
class EventDefinition:
    id: str
    name: str


@dataclass(frozen=True)
class Experiment:
    id: int | str
    name: str
    feature_flag_key: str
    start_date: str
    end_date: str
    archived: bool
    raw: dict[str, Any]


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {personal_api_key()}",
        "Content-Type": "application/json",
    }


def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> Any:
    """Low-level HTTP. Only GET and POST (query) are used by public helpers."""
    method = method.upper()
    if method not in {"GET", "POST"}:
        raise PostHogClientError(f"Read-only client refuses method {method}")
    if method == "POST" and "/query/" not in path:
        raise PostHogClientError("Read-only client only allows POST to /query/")
    url = path if path.startswith("http") else urljoin(host() + "/", path.lstrip("/"))
    try:
        resp = requests.request(
            method,
            url,
            headers=_headers(),
            params=params,
            json=json_body,
            timeout=60,
        )
    except requests.RequestException as exc:
        raise PostHogClientError(f"PostHog request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise PostHogClientError(f"PostHog {method} {url} → {resp.status_code}: {resp.text[:400]}")
    if not resp.content:
        return None
    return resp.json()


def _paginate(path: str, *, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Follow ``next`` cursors until exhausted."""
    results: list[dict[str, Any]] = []
    url: str | None = path if path.startswith("http") else path
    query = dict(params or {})
    while url:
        data = _request("GET", url, params=query if not url.startswith("http") else None)
        query = {}  # next URL already encodes params
        if isinstance(data, list):
            results.extend(item for item in data if isinstance(item, dict))
            break
        if not isinstance(data, dict):
            break
        batch = data.get("results")
        if isinstance(batch, list):
            results.extend(item for item in batch if isinstance(item, dict))
        nxt = data.get("next")
        url = str(nxt) if nxt else None
    return results


def list_feature_flags() -> list[FeatureFlag]:
    pid = project_id()
    rows = _paginate(f"/api/projects/{pid}/feature_flags/", params={"limit": 100})
    out: list[FeatureFlag] = []
    for row in rows:
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        out.append(
            FeatureFlag(
                id=row.get("id") or key,
                key=key,
                name=str(row.get("name") or key),
                active=bool(row.get("active", True)),
            )
        )
    return out


def list_event_definitions() -> list[EventDefinition]:
    pid = project_id()
    rows = _paginate(f"/api/projects/{pid}/event_definitions/", params={"limit": 100})
    out: list[EventDefinition] = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        out.append(EventDefinition(id=str(row.get("id") or name), name=name))
    return out


def list_experiments() -> list[Experiment]:
    pid = project_id()
    rows = _paginate(f"/api/projects/{pid}/experiments/", params={"limit": 100})
    out: list[Experiment] = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name and row.get("id") is None:
            continue
        flag = row.get("feature_flag") or {}
        flag_key = ""
        if isinstance(flag, dict):
            flag_key = str(flag.get("key") or "")
        if not flag_key:
            flag_key = str(row.get("feature_flag_key") or "")
        out.append(
            Experiment(
                id=row.get("id") or name,
                name=name or str(row.get("id")),
                feature_flag_key=flag_key,
                start_date=str(row.get("start_date") or "")[:10],
                end_date=str(row.get("end_date") or "")[:10],
                archived=bool(row.get("archived", False)),
                raw=row,
            )
        )
    return out


def list_insights(*, search: str | None = None) -> list[dict[str, Any]]:
    pid = project_id()
    params: dict[str, Any] = {"limit": 100}
    if search:
        params["search"] = search
    return _paginate(f"/api/projects/{pid}/insights/", params=params)


def find_insight_by_name(name: str) -> dict[str, Any] | None:
    """Return the first insight whose name matches (case-insensitive)."""
    target = name.strip().lower()
    if not target:
        return None
    for row in list_insights(search=name):
        if str(row.get("name") or "").strip().lower() == target:
            return row
    # Broader scrape if search miss
    for row in list_insights():
        if str(row.get("name") or "").strip().lower() == target:
            return row
    return None


def query_hogql(sql: str, *, name: str = "company_brain_query") -> dict[str, Any]:
    """Run a HogQL query via POST /query/. Not for bulk export."""
    pid = project_id()
    return _request(
        "POST",
        f"/api/projects/{pid}/query/",
        json_body={
            "query": {"kind": "HogQLQuery", "query": sql},
            "name": name,
        },
    )


def query_results(sql: str, *, name: str = "company_brain_query") -> list[list[Any]]:
    """Return ``results`` rows from a HogQL query (empty list on miss)."""
    data = query_hogql(sql, name=name)
    if not isinstance(data, dict):
        return []
    rows = data.get("results")
    if isinstance(rows, list):
        return rows
    return []


def has_events_since_days(days: int = 30) -> bool:
    """Cheap existence check for onboarding (any event in the lookback window)."""
    days = max(1, int(days))
    sql = f"SELECT count() FROM events WHERE timestamp >= now() - INTERVAL {days} DAY LIMIT 1"
    rows = query_results(sql, name="has_events_check")
    if not rows:
        return False
    try:
        return int(rows[0][0]) > 0
    except (IndexError, TypeError, ValueError):
        return False


def event_counts(*, event_names: list[str], days: int) -> dict[str, int]:
    """Count events by name over the last ``days`` days."""
    if not event_names:
        return {}
    days = max(1, int(days))
    # Escape single quotes in event names for HogQL string literals
    literals = ", ".join("'" + n.replace("'", "\\'") + "'" for n in event_names)
    sql = (
        f"SELECT event, count() AS c FROM events "
        f"WHERE timestamp >= now() - INTERVAL {days} DAY "
        f"AND event IN ({literals}) "
        f"GROUP BY event"
    )
    out = {name: 0 for name in event_names}
    for row in query_results(sql, name=f"event_counts_{days}d"):
        if not row or len(row) < 2:
            continue
        out[str(row[0])] = int(row[1] or 0)
    return out


def pageview_count(*, paths: list[str], days: int) -> int:
    """Count ``$pageview`` events whose pathname / URL matches any of ``paths``."""
    days = max(1, int(days))
    if not paths:
        return 0
    clauses = []
    for path in paths:
        p = path.replace("'", "\\'")
        if p == "/":
            clauses.append(
                "(coalesce(properties.$pathname, '/') IN ('/', '') "
                "OR properties.$current_url LIKE '%/')"
            )
        else:
            clauses.append(
                f"(properties.$pathname = '{p}' OR properties.$current_url LIKE '%{p}%')"
            )
    where = " OR ".join(clauses)
    sql = (
        f"SELECT count() FROM events WHERE event = '$pageview' "
        f"AND timestamp >= now() - INTERVAL {days} DAY AND ({where})"
    )
    rows = query_results(sql, name=f"pageview_count_{days}d")
    if not rows:
        return 0
    try:
        return int(rows[0][0] or 0)
    except (IndexError, TypeError, ValueError):
        return 0
