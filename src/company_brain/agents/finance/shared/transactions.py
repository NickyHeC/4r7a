"""Common transaction record shape and finance helpers.

Specialist agents normalise platform data (Mercury, Ramp) into the record
shape documented below so managers can aggregate across platforms uniformly.

Normalised transaction record::

    {
        "name": str,            # counterparty / merchant / vendor
        "amount": float,        # signed: positive = inflow, negative = outflow
        "date": str,            # YYYY-MM-DD
        "source": str,          # "Mercury", "Mercury Credit", "Ramp", "Ramp Bill Pay"
        "category": str,        # platform-native category (optional)
        "qb_categories": list,  # Ramp QuickBooks categories (optional)
        "sk_category": str,     # Ramp merchant category (optional)
        "account": str,         # account / card label (optional)
    }
"""

from __future__ import annotations

import calendar
from datetime import date, datetime
from typing import Any

from . import categories as cat

MONTH_NAMES = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def month_range(month_str: str) -> tuple[str, str]:
    """``2026-04`` -> ``(2026-04-01, 2026-04-30)`` (inclusive)."""
    year, month = int(month_str[:4]), int(month_str[5:7])
    last = calendar.monthrange(year, month)[1]
    return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last:02d}"


def quarter_months(quarter_str: str) -> list[str]:
    """``2026-Q2`` -> ``['2026-04', '2026-05', '2026-06']``."""
    year = int(quarter_str[:4])
    q = int(quarter_str[-1])
    start_m = (q - 1) * 3 + 1
    return [f"{year}-{m:02d}" for m in range(start_m, start_m + 3)]


def current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def previous_month(today: date | None = None) -> str:
    today = today or date.today()
    year, month = today.year, today.month
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def current_quarter(today: date | None = None) -> str:
    today = today or date.today()
    return f"{today.year}-Q{(today.month - 1) // 3 + 1}"


def previous_quarter(today: date | None = None) -> str:
    today = today or date.today()
    q = (today.month - 1) // 3 + 1
    if q == 1:
        return f"{today.year - 1}-Q4"
    return f"{today.year}-Q{q - 1}"


def month_label(month_str: str) -> str:
    """``2026-04`` -> ``April 2026``."""
    return f"{MONTH_NAMES[int(month_str[5:7])]} {month_str[:4]}"


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def fmt_money(val: float) -> str:
    """Format a dollar value; negatives in parentheses."""
    if val < 0:
        return f"(${abs(val):,.2f})"
    return f"${val:,.2f}"


# ---------------------------------------------------------------------------
# Metrics (shared by quarterly_calculation + onboarding)
# ---------------------------------------------------------------------------


def compute_monthly_metrics(txns: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the core financial metrics for a month of normalised txns.

    Sign convention: positive amount = inflow, negative = outflow.
    """
    revenue = 0.0
    total_expenses = 0.0
    interest_expense = 0.0
    tax_expense = 0.0
    revenue_items: list[dict] = []
    expense_items: list[dict] = []

    for t in txns:
        name = t.get("name", "")
        amount = t["amount"]
        if amount > 0:
            revenue += amount
            revenue_items.append(t)
        elif amount < 0:
            expense = abs(amount)
            total_expenses += expense
            expense_items.append(t)
            if cat.is_interest(name):
                interest_expense += expense
            if cat.is_tax(name):
                tax_expense += expense

    net_income = revenue - total_expenses
    ebitda = net_income + interest_expense + tax_expense
    return {
        "revenue": revenue,
        "total_expenses": total_expenses,
        "interest_expense": interest_expense,
        "tax_expense": tax_expense,
        "net_income": net_income,
        "ebitda": ebitda,
        "net_burn": net_income,
        "revenue_items": revenue_items,
        "expense_items": expense_items,
        "transaction_count": len(txns),
    }


def find_uncategorized(
    txns: list[dict[str, Any]], keyword_maps: dict[str, dict[str, list[str]]]
) -> list[dict[str, Any]]:
    """Return outflow transactions that classify as Uncategorized."""
    out: list[dict] = []
    for t in txns:
        if t.get("amount", 0) < 0 and cat.classify_budget(t, keyword_maps) == cat.UNCATEGORIZED:
            out.append(t)
    return out
