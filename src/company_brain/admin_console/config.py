"""Load ``config/admin_console.yaml``."""

from __future__ import annotations

from typing import Any

from company_brain.config import load_yaml_config


def load_admin_console_config() -> dict[str, Any]:
    return dict(load_yaml_config("admin_console") or {})


def bind_host() -> str:
    return str(load_admin_console_config().get("bind_host") or "127.0.0.1")


def bind_port() -> int:
    try:
        return int(load_admin_console_config().get("bind_port") or 8780)
    except (TypeError, ValueError):
        return 8780


def stale_minutes() -> int:
    try:
        return max(1, int(load_admin_console_config().get("stale_minutes") or 10))
    except (TypeError, ValueError):
        return 10


def manager_catalog() -> list[dict[str, str]]:
    rows = load_admin_console_config().get("managers") or []
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "label": str(row.get("label") or name).strip(),
            }
        )
    return out


def dispatch_jobs() -> list[dict[str, Any]]:
    rows = load_admin_console_config().get("dispatch") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        job_id = str(row.get("id") or "").strip()
        agent = str(row.get("agent") or "").strip()
        if not job_id or not agent:
            continue
        out.append(
            {
                "id": job_id,
                "label": str(row.get("label") or job_id).strip(),
                "agent": agent,
                "kwargs": dict(row.get("kwargs") or {}),
            }
        )
    return out


def dispatch_job(job_id: str) -> dict[str, Any] | None:
    for job in dispatch_jobs():
        if job["id"] == job_id:
            return job
    return None
