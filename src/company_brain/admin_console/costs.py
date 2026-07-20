"""LLM operating cost snapshot for the Costs pane."""

from __future__ import annotations

from datetime import datetime
from typing import Any

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
        # Also try current/previous month paths even if list is empty
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
    out: dict[str, Any] = {
        "budget": status,
        "expense_rel": expense_rel or "",
        "expense_body": expense_body,
        "reconcile": None,
    }
    if reconcile:
        try:
            from company_brain.llm.reconcile import reconciliation_report

            out["reconcile"] = reconciliation_report()
        except Exception as exc:
            out["reconcile"] = {"status": "error", "error": str(exc)[:300]}
    return out
