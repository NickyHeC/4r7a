"""Mercury Card Spend Agent — categorize Mercury IO card spend for a time frame.

Reads Mercury IO credit-card transactions within a specified time frame and
categorizes spend using Mercury's own transaction categories (general ledger /
category classification). Outflows only (card spend).

SDK: Neither (deterministic Python via the Mercury CLI wrapper). Mercury already
provides per-transaction categories, so no LLM classification is required.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from company_brain.agents.base import BaseAgent

from . import mercury_client as mc

AGENT_KEY = "mercury_card_spend"


class MercuryCardSpendAgent(BaseAgent):
    """Fetch and categorize Mercury IO card spend for a date range."""

    name = "finance_mercury_card_spend"

    def run(self, *, start: str, end: str, **kwargs: Any) -> dict[str, Any]:
        """Return normalised card transactions and a category breakdown."""
        self.logger.info("Fetching Mercury IO card spend %s -> %s", start, end)
        credit_accounts = mc.list_credit_accounts()

        records: list[dict] = []
        for t in mc.list_all_transactions(credit_accounts, start=start, end=end):
            if mc.is_internal_transfer(t):
                continue
            amount = t.get("amount", 0) or 0
            if amount >= 0:
                continue  # card spend = outflow
            records.append({
                "name": mc.txn_counterparty(t),
                "amount": amount,
                "date": mc.txn_date(t),
                "source": "Mercury Credit",
                "category": mc.txn_category(t),
                "account": t.get("_account_name", ""),
                "kind": t.get("kind", ""),
            })

        by_category: dict[str, float] = defaultdict(float)
        for r in records:
            by_category[r["category"]] += abs(r["amount"])

        total = sum(abs(r["amount"]) for r in records)
        self.logger.info("Fetched %d card txns totalling %s", len(records), mc.fmt_money(total))
        return {
            "start": start,
            "end": end,
            "transactions": records,
            "by_category": dict(by_category),
            "total_spend": total,
        }
