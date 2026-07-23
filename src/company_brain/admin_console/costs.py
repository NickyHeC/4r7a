"""LLM + estimated cloud VM operating cost snapshot for the Costs pane."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.admin_console.config import (
    load_admin_console_config,
    manager_catalog,
    stale_minutes,
)
from company_brain.admin_console.heartbeats import HEARTBEAT_PREFIX, status_rows
from company_brain.agents.gates import StateStore
from company_brain.llm.budget import budget_status
from company_brain.wiki.store import LocalWikiStore


def latest_expense_rel() -> str | None:
    """Return newest ``admin/llm-expense/YYYY-MM.md`` if present."""
    store = LocalWikiStore()
    prefix = "admin/llm-expense/"
    months: list[str] = []
    for rel in store.list():
        if rel.startswith(prefix) and rel.endswith(".md"):
            months.append(rel)
    if not months:
        now = datetime.now()
        for offset in (0, 1):
            y = now.year
            m = now.month - offset
            if m <= 0:
                y -= 1
                m += 12
            candidate = f"admin/llm-expense/{y:04d}-{m:02d}.md"
            try:
                store.read(candidate)
                return candidate
            except FileNotFoundError:
                continue
        return None
    months.sort(reverse=True)
    return months[0]


def _vm_config() -> dict[str, Any]:
    raw = load_admin_console_config().get("costs") or {}
    if not isinstance(raw, dict):
        raw = {}
    try:
        hourly = float(raw.get("vm_hourly_usd") or 0.0)
    except (TypeError, ValueError):
        hourly = 0.0
    return {
        "vm_hourly_usd": max(0.0, hourly),
        "label": str(raw.get("vm_estimate_label") or "estimate (not invoice)"),
    }


def hours_elapsed_in_month(*, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return max(0.0, (now - start).total_seconds() / 3600.0)


def vm_cost_snapshot(
    *,
    store: StateStore | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Rough VM cost from active manager heartbeats × configured hourly rate.

    Assumes each manager with a fresh heartbeat is an always-on process for the
    month-to-date. Labeled as an estimate until provider invoice reconcile exists.
    """
    cfg = _vm_config()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    store = store or StateStore()
    rows = status_rows(store=store, now=now)
    active = [r for r in rows if r.get("state") == "ok"]
    # Also count heartbeats for managers not in catalog
    catalog_names = {r["name"] for r in rows}
    for key in store.keys(prefix=HEARTBEAT_PREFIX):
        name = key.removeprefix(HEARTBEAT_PREFIX)
        if name not in catalog_names:
            # treat unknown with any heartbeat as potential
            catalog_names.add(name)
    hours = hours_elapsed_in_month(now=now)
    active_count = len(active)
    hourly = float(cfg["vm_hourly_usd"])
    estimate = round(active_count * hours * hourly, 4) if hourly > 0 else 0.0
    return {
        "enabled": hourly > 0,
        "vm_hourly_usd": hourly,
        "label": cfg["label"],
        "active_managers": active_count,
        "catalog_managers": len(manager_catalog()),
        "stale_minutes": stale_minutes(),
        "hours_elapsed_month": round(hours, 2),
        "estimate_month_usd": estimate,
        "is_estimate": True,
    }


def costs_snapshot(*, reconcile: bool = False) -> dict[str, Any]:
    status = budget_status()
    expense_rel = latest_expense_rel()
    expense_body = ""
    if expense_rel:
        try:
            from company_brain.wiki.publish import read_wiki_page

            expense_body = read_wiki_page(expense_rel)
        except FileNotFoundError:
            expense_body = ""
    vm = vm_cost_snapshot()
    llm_spent = float(status.get("spent_usd") or 0.0)
    total = round(llm_spent + float(vm.get("estimate_month_usd") or 0.0), 4)
    out: dict[str, Any] = {
        "budget": status,
        "expense_rel": expense_rel or "",
        "expense_body": expense_body,
        "reconcile": None,
        "vm": vm,
        "total_month_usd": total,
        "total_is_estimate": True,
    }
    if reconcile:
        try:
            from company_brain.llm.reconcile import reconciliation_report

            out["reconcile"] = reconciliation_report()
        except Exception as exc:
            out["reconcile"] = {"status": "error", "error": str(exc)[:300]}
    return out
