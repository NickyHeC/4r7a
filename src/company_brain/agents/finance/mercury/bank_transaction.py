"""Bank Transaction Agent — pull Mercury bank transactions for a time frame.

Pulls both inbound and outbound transactions across all active Mercury bank
accounts within a specified time frame, normalising them into the shared
transaction record shape. Internal/treasury transfers are excluded so the
output reflects real economic activity.

SDK: Neither (deterministic Python via the Mercury CLI wrapper). Pure data pull.
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent

from . import mercury_client as mc

AGENT_KEY = "bank_transaction"


class BankTransactionAgent(BaseAgent):
    """Fetch normalised Mercury bank transactions for a date range."""

    name = "finance_bank_transaction"

    def run(
        self,
        *,
        start: str,
        end: str,
        include_inbound: bool = True,
        include_outbound: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return normalised transactions between ``start`` and ``end`` (YYYY-MM-DD)."""
        self.logger.info("Fetching Mercury bank transactions %s -> %s", start, end)
        accounts = [a for a in mc.list_accounts() if a.get("status") == "active"]

        records: list[dict] = []
        for t in mc.list_all_transactions(accounts, start=start, end=end):
            if mc.is_internal_transfer(t):
                continue
            amount = t.get("amount", 0) or 0
            if amount > 0 and not include_inbound:
                continue
            if amount < 0 and not include_outbound:
                continue
            records.append({
                "name": mc.txn_counterparty(t),
                "amount": amount,
                "date": mc.txn_date(t),
                "source": "Mercury",
                "category": mc.txn_category(t),
                "account": t.get("_account_name", ""),
                "kind": t.get("kind", ""),
            })

        inbound = sum(1 for r in records if r["amount"] > 0)
        outbound = sum(1 for r in records if r["amount"] < 0)
        self.logger.info("Fetched %d txns (%d in, %d out)", len(records), inbound, outbound)
        return {
            "start": start,
            "end": end,
            "transactions": records,
            "inbound_count": inbound,
            "outbound_count": outbound,
        }
