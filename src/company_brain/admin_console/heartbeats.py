"""Persistent-manager heartbeat registry in ``config/state.json``."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.admin_console.config import manager_catalog, stale_minutes
from company_brain.agents.gates import StateStore

HEARTBEAT_PREFIX = "admin_console:heartbeat:"
DISPATCH_PREFIX = "admin_console:last_dispatch:"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def record_heartbeat(
    name: str,
    *,
    detail: str | None = None,
    store: StateStore | None = None,
) -> dict[str, Any]:
    """Record that a persistent manager is alive (call each loop tick)."""
    store = store or StateStore()
    name = name.strip()
    if not name:
        raise ValueError("heartbeat name required")
    payload = {
        "name": name,
        "at": _utcnow().isoformat(),
        "detail": detail or "",
    }
    store.set(f"{HEARTBEAT_PREFIX}{name}", payload)
    return payload


def record_dispatch(
    name: str,
    *,
    result_status: str = "ok",
    store: StateStore | None = None,
) -> dict[str, Any]:
    store = store or StateStore()
    name = name.strip()
    payload = {
        "name": name,
        "at": _utcnow().isoformat(),
        "status": result_status,
    }
    store.set(f"{DISPATCH_PREFIX}{name}", payload)
    return payload


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def status_rows(
    *,
    store: StateStore | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Catalog + heartbeat/dispatch state for the Status pane."""
    store = store or StateStore()
    now = now or _utcnow()
    stale_s = stale_minutes() * 60
    rows: list[dict[str, Any]] = []
    for entry in manager_catalog():
        name = entry["name"]
        hb = store.get(f"{HEARTBEAT_PREFIX}{name}") or {}
        disp = store.get(f"{DISPATCH_PREFIX}{name}") or {}
        if not isinstance(hb, dict):
            hb = {}
        if not isinstance(disp, dict):
            disp = {}
        hb_at = _parse_iso(hb.get("at") if isinstance(hb.get("at"), str) else None)
        if hb_at is None:
            state = "no_heartbeat"
            age_seconds = None
        else:
            if hb_at.tzinfo is None:
                hb_at = hb_at.replace(tzinfo=timezone.utc)
            age_seconds = max(0, int((now - hb_at.astimezone(timezone.utc)).total_seconds()))
            state = "ok" if age_seconds <= stale_s else "stale"
        rows.append(
            {
                "name": name,
                "label": entry["label"],
                "state": state,
                "heartbeat_at": hb.get("at") or "",
                "heartbeat_detail": hb.get("detail") or "",
                "age_seconds": age_seconds,
                "last_dispatch_at": disp.get("at") or "",
                "last_dispatch_status": disp.get("status") or "",
            }
        )
    return rows
