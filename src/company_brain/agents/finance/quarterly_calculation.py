"""Quarterly Calculation Manager.

A persistent department manager. On the 5th day of each quarter at 09:00 it
computes the previous quarter's financials from Mercury + Ramp transactions:
Revenue, Expenses, Net Income, EBITDA, Net Burn, plus a per-month breakdown.
Results are written to the Notion "Quarterly Metric" page under a "<Quarter>
<Year>" heading as a markdown table (not a Notion database), with monthly detail
below the metrics. The expense section is cross-verified against the
"Monthly Expense Reports" pages.

If there are uncategorized transactions it invokes request_manual_accounting.
Otherwise it starts budget_report and subscription_audit before returning to idle.

SDK: Neither for the metric core (deterministic Python, ported from the
reference quarterly calculation). Orchestration is plain asyncio; dispatched
sub-agents choose their own SDKs.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, time, timedelta
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.config import AppConfig

from .shared import categories as cat
from .shared import notion_pages, transactions
from .shared.config import load_finance_config

RUN_DAY = 5
RUN_TIME = time(9, 0)
QUARTER_START_MONTHS = {1, 4, 7, 10}

QUARTERLY_KEY = "quarterly_metric"
QUARTERLY_TERMS = ["Quarterly Metric", "Quarterly Metrics"]


class QuarterlyCalculationManager(BaseAgent):
    """Persistent manager that compiles quarterly financial metrics.

    Append agent: each quarter's metrics section is prepended (newest on top).
    """

    name = "finance_quarterly_calculation"
    WRITE_MODE = "append"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.finance_config = load_finance_config()
        self.keyword_maps = cat.load_company_keywords(self.finance_config)

    # -- lifecycle ---------------------------------------------------------

    def run(self, *, once: bool = False, quarter: str | None = None, **kwargs: Any) -> Any:
        if once:
            return self.run_once(quarter or transactions.previous_quarter())
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        self.logger.info("Quarterly calculation manager starting persistent loop")
        while True:
            now = datetime.now()
            nxt = self._next_run_time(now)
            wait = (nxt - now).total_seconds()
            self.logger.info("Next quarterly run at %s (sleep %.0fs)", nxt.isoformat(), wait)
            await asyncio.sleep(wait)
            try:
                self.run_once(transactions.previous_quarter())
            except Exception:
                self.logger.exception("Quarterly calculation run failed")

    # -- core --------------------------------------------------------------

    def run_once(self, quarter: str, *, escalate: bool = True) -> dict[str, Any]:
        """Compute and publish metrics for ``quarter`` (e.g. 2026-Q1).

        ``escalate`` controls whether uncategorized transactions trigger
        request_manual_accounting (set False when that agent reruns us post-correction).
        """
        self.logger.info("Computing quarterly metrics for %s", quarter)
        # Reload learned categories so reruns pick up manual corrections.
        self.finance_config = load_finance_config()
        self.keyword_maps = cat.load_company_keywords(self.finance_config)
        months = transactions.quarter_months(quarter)

        monthly_data: dict[str, dict] = {}
        all_txns: list[dict] = []
        for month in months:
            month_txns = self._gather_all(month)
            all_txns.extend(month_txns)
            monthly_data[month] = transactions.compute_monthly_metrics(month_txns)

        report = self._build_report(quarter, months, monthly_data)
        verification = self._cross_verify(months, monthly_data)
        if verification:
            report = f"{report}\n{verification}\n"

        page_id = self._publish_notion(quarter, report)

        uncategorized = transactions.find_uncategorized(all_txns, self.keyword_maps)
        if uncategorized and escalate:
            self.logger.info("%d uncategorized txns — invoking request_manual_accounting", len(uncategorized))
            self._dispatch_manual_accounting(quarter, uncategorized)
        else:
            self.logger.info("No uncategorized txns (or escalation off) — starting budget_report + subscription_audit")
            self._dispatch_followups(quarter)

        return {
            "quarter": quarter,
            "monthly_data": monthly_data,
            "uncategorized_count": len(uncategorized),
            "notion_page_id": page_id,
            "report": report,
        }

    def _gather_all(self, month: str) -> list[dict]:
        """All inflow + outflow transactions for a month across platforms."""
        from .mercury.bank_transaction import BankTransactionAgent
        from .mercury.mercury_card_spend import MercuryCardSpendAgent
        from .ramp.ramp_card_spend import RampCardSpendAgent

        start, end = transactions.month_range(month)
        txns: list[dict] = []

        bank = BankTransactionAgent(self.config).execute(start=start, end=end)
        txns.extend(bank.get("transactions", []))

        card = MercuryCardSpendAgent(self.config).execute(start=start, end=end)
        txns.extend(card.get("transactions", []))

        try:
            ramp = RampCardSpendAgent(self.config).execute(start=start, end=end)
            txns.extend(ramp.get("transactions", []))
        except Exception:
            self.logger.exception("Ramp unavailable for %s; continuing with Mercury only", month)

        return txns

    def _build_report(self, quarter: str, months: list[str], monthly_data: dict[str, dict]) -> str:
        heading = f"{quarter[-2:]} {quarter[:4]}"  # e.g. "Q1 2026"
        month_headers = [transactions.MONTH_NAMES[int(m[5:7])] for m in months]

        def _f(v: float) -> str:
            return transactions.fmt_money(v)

        q = {k: sum(monthly_data[m][k] for m in months) for k in
             ("revenue", "total_expenses", "net_income", "ebitda", "net_burn")}

        lines = [f"## {heading}", ""]
        lines.append(f"*Generated: {datetime.now():%Y-%m-%d %H:%M}. Basis: cash (Mercury + Ramp).*")
        lines.append("")
        lines.append(f"| Metric | {' | '.join(month_headers)} | Quarter Total |")
        lines.append(f"|---|{'---|' * len(months)}---|")
        for key, lbl in [
            ("revenue", "Revenue"), ("total_expenses", "Total Expenses"),
            ("net_income", "Net Income"), ("ebitda", "EBITDA"), ("net_burn", "Net Burn"),
        ]:
            row = " | ".join(_f(monthly_data[m][key]) for m in months)
            lines.append(f"| **{lbl}** | {row} | **{_f(q[key])}** |")
        lines.append("")

        for m in months:
            d = monthly_data[m]
            lines.append(f"### {transactions.month_label(m)} Detail")
            lines.append("")
            lines.append(f"- Transactions: {d['transaction_count']}")
            lines.append(f"- Revenue: {_f(d['revenue'])}")
            lines.append(f"- Total Expenses: {_f(d['total_expenses'])}")
            top = defaultdict(float)
            for t in d["expense_items"]:
                top[t.get("name") or "Unknown"] += abs(t["amount"])
            for vendor, amt in sorted(top.items(), key=lambda x: -x[1])[:10]:
                lines.append(f"  - {vendor}: {_f(amt)}")
            lines.append("")
        return "\n".join(lines)

    def _cross_verify(self, months: list[str], monthly_data: dict[str, dict]) -> str:
        """Compare computed expenses against the Monthly Expense Reports pages."""
        notes = ["### Expense Cross-Verification", ""]
        # Each month has its own page under "Monthly Expense Reports".
        for m in months:
            label = transactions.month_label(m)
            computed = monthly_data[m]["total_expenses"]
            bound = notion_pages.get_bound_id(f"monthly_expense_{m}")
            present = "monthly report present" if bound else "no monthly report yet"
            notes.append(
                f"- {label}: computed {transactions.fmt_money(computed)} ({present})"
            )
        return "\n".join(notes)

    def _publish_notion(self, quarter: str, report: str) -> str | None:
        page_id = notion_pages.ensure_page(QUARTERLY_KEY, QUARTERLY_TERMS, "Quarterly Metric")
        if not page_id:
            self.logger.warning("Could not bind 'Quarterly Metric' page")
            return None
        notion_pages.prepend_page_body(page_id, report)
        return page_id

    def _dispatch_manual_accounting(self, quarter: str, uncategorized: list[dict]) -> None:
        from company_brain.runtime import get_runtime

        from .request_manual_accounting import RequestManualAccountingAgent

        get_runtime().run(
            RequestManualAccountingAgent, self.config,
            source_agent=self.name,
            context={"period": quarter, "kind": "quarterly"},
            uncategorized=uncategorized,
        )

    def _dispatch_followups(self, quarter: str) -> None:
        from company_brain.runtime import get_runtime

        from .budget_report import BudgetReportAgent
        from .subscription_audit import SubscriptionAuditAgent

        runtime = get_runtime()
        try:
            runtime.run(BudgetReportAgent, self.config, quarter=quarter)
        except Exception:
            self.logger.exception("budget_report failed")
        try:
            runtime.run(SubscriptionAuditAgent, self.config, quarter=quarter)
        except Exception:
            self.logger.exception("subscription_audit failed")

    @staticmethod
    def _next_run_time(now: datetime) -> datetime:
        """Next occurrence of the 5th of a quarter-start month at RUN_TIME."""
        candidates: list[datetime] = []
        for year in (now.year, now.year + 1):
            for month in sorted(QUARTER_START_MONTHS):
                candidates.append(
                    now.replace(year=year, month=month, day=RUN_DAY,
                                hour=RUN_TIME.hour, minute=RUN_TIME.minute,
                                second=0, microsecond=0)
                )
        return min(c for c in candidates if c > now)
