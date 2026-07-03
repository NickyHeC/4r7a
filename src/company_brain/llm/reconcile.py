"""Reconcile tracked LLM usage against finance card vendor bills (fallback).

Primary tracking is API token hooks in ``record_usage()``. This module closes the
loop monthly by summing Anthropic/OpenAI charges on Mercury (and Ramp when
available) and comparing to ``config/state.json`` usage ledger entries.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.finance.shared.transactions import month_range
from company_brain.agents.gates import StateStore
from company_brain.llm.budget import USAGE_PREFIX, _month_key

logger = logging.getLogger(__name__)

RECONCILE_PREFIX = "llm_budget:reconcile:"

# Vendor name substrings -> canonical key (lowercase counterparty match).
LLM_VENDOR_TOKENS: dict[str, tuple[str, ...]] = {
    "anthropic": ("anthropic",),
    "openai": ("openai", "chatgpt"),
}

DEFAULT_DRIFT_WARN_PERCENT = 25.0


def match_llm_vendor(counterparty: str) -> str | None:
    lower = (counterparty or "").lower()
    for vendor, tokens in LLM_VENDOR_TOKENS.items():
        if any(token in lower for token in tokens):
            return vendor
    return None


def _mercury_llm_spend(start: str, end: str) -> dict[str, float]:
    from company_brain.agents.finance.mercury import mercury_client as mc

    totals: dict[str, float] = defaultdict(float)
    credit_accounts = mc.list_credit_accounts()
    for txn in mc.list_all_transactions(credit_accounts, start=start, end=end):
        if mc.is_internal_transfer(txn):
            continue
        amount = txn.get("amount", 0) or 0
        if amount >= 0:
            continue
        vendor = match_llm_vendor(mc.txn_counterparty(txn))
        if vendor:
            totals[vendor] += abs(float(amount))
    return dict(totals)


def sum_vendor_llm_spend(*, month: str | None = None) -> dict[str, Any]:
    """Sum LLM vendor card spend for ``month`` (``YYYY-MM``, default current)."""
    month = month or _month_key()
    start, end = month_range(month)
    by_vendor: dict[str, float] = defaultdict(float)
    sources: list[str] = []

    try:
        for vendor, amount in _mercury_llm_spend(start, end).items():
            by_vendor[vendor] += amount
        if by_vendor:
            sources.append("mercury")
    except Exception:
        logger.debug("Mercury LLM vendor reconcile unavailable", exc_info=True)

    total = sum(by_vendor.values())
    return {
        "month": month,
        "by_vendor": dict(by_vendor),
        "total_usd": total,
        "sources": sources,
    }


def tracked_usage_for_month(
    *,
    month: str | None = None,
    store: StateStore | None = None,
) -> dict[str, float]:
    store = store or StateStore()
    month = month or _month_key()
    raw = store.get(f"{USAGE_PREFIX}{month}") or {}
    categories = raw.get("categories") or {}
    return {
        "input_tokens": float(raw.get("input_tokens") or 0),
        "output_tokens": float(raw.get("output_tokens") or 0),
        "estimated_usd": float(raw.get("estimated_usd") or 0),
        "runtime_usd": float((categories.get("runtime") or {}).get("estimated_usd") or 0),
        "builder_usd": float((categories.get("builder") or {}).get("estimated_usd") or 0),
    }


def reconciliation_report(
    *,
    month: str | None = None,
    store: StateStore | None = None,
    drift_warn_percent: float = DEFAULT_DRIFT_WARN_PERCENT,
) -> dict[str, Any]:
    """Compare tracked usage vs card vendor totals for a month."""
    store = store or StateStore()
    month = month or _month_key()
    tracked = tracked_usage_for_month(month=month, store=store)
    vendor = sum_vendor_llm_spend(month=month)
    vendor_total = float(vendor["total_usd"])
    tracked_total = float(tracked["estimated_usd"])
    drift_usd = round(vendor_total - tracked_total, 4)
    drift_percent = (
        round(abs(drift_usd) / vendor_total * 100, 1) if vendor_total > 0 else 0.0
    )
    report = {
        "month": month,
        "tracked_usd": tracked_total,
        "vendor_usd": vendor_total,
        "drift_usd": drift_usd,
        "drift_percent": drift_percent,
        "drift_warn_percent": drift_warn_percent,
        "vendor_by_source": vendor["by_vendor"],
        "vendor_sources": vendor["sources"],
        "tracked": tracked,
        "warn": vendor_total > 0 and drift_percent >= drift_warn_percent,
    }
    checked_at = datetime.now(timezone.utc).isoformat()
    store.set(f"{RECONCILE_PREFIX}{month}", {**report, "checked_at": checked_at})
    return report


def format_reconciliation(report: dict[str, Any]) -> str:
    lines = [
        f"Month {report['month']}: tracked ${report['tracked_usd']:.2f}, "
        f"vendor bills ${report['vendor_usd']:.2f} "
        f"(drift ${report['drift_usd']:+.2f}, {report['drift_percent']:.1f}%)",
    ]
    if report.get("vendor_by_source"):
        parts = [f"{k} ${v:.2f}" for k, v in sorted(report["vendor_by_source"].items())]
        lines.append(f"  Vendors: {', '.join(parts)}")
    if report.get("vendor_sources"):
        lines.append(f"  Sources: {', '.join(report['vendor_sources'])}")
    if report["tracked_usd"] > 0:
        lines.append(
            f"  Tracked split: runtime ${report['tracked']['runtime_usd']:.2f}, "
            f"builder ${report['tracked']['builder_usd']:.2f}",
        )
    return "\n".join(lines)
