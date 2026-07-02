"""Monthly Expense Manager.

A persistent department manager. On the 1st of each month at 08:00 it dispatches
the transaction specialists (Mercury bank, Mercury card, Ramp card) for the
previous month, sorts outbound spend into budget categories, posts the compiled
report to Slack #finance, and creates a Notion page "<Month> Expense Report"
under the "Monthly Expense Reports" page. Idles between runs.

SDK: Anthropic Claude Agent SDK (optional narrative polish of the report) layered
on deterministic categorization. Orchestration (dispatch + schedule) is plain
asyncio, mirroring the engineering github_manager.

If any transactions are uncategorized, it starts request_manual_accounting to
solicit human help before the report is considered final.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, time
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.config import AppConfig

from .shared import categories as cat
from .shared import notion_pages, transactions
from .shared.config import load_finance_config

RUN_DAY = 1
RUN_TIME = time(8, 0)

PARENT_KEY = "monthly_expense_reports"
PARENT_TERMS = ["Monthly Expense Reports", "Monthly Expense Report"]


class MonthlyExpenseManager(BaseAgent):
    """Persistent manager that compiles a monthly expense report.

    Update agent: each month gets its own page under "Monthly Expense Reports",
    overwritten in place on re-run.
    """

    name = "finance_monthly_expense"
    WRITE_MODE = "update"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.finance_config = load_finance_config()
        self.keyword_maps = cat.load_company_keywords(self.finance_config)

    # -- lifecycle ---------------------------------------------------------

    def run(self, *, once: bool = False, month: str | None = None, **kwargs: Any) -> Any:
        """Start the persistent loop, or run a single month when ``once``."""
        if once:
            return self.run_once(month or transactions.previous_month())
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        self.logger.info("Monthly expense manager starting persistent loop")
        while True:
            now = datetime.now()
            nxt = self._next_run_time(now)
            wait = (nxt - now).total_seconds()
            self.logger.info("Next monthly run at %s (sleep %.0fs)", nxt.isoformat(), wait)
            await asyncio.sleep(wait)
            try:
                self.run_once(transactions.previous_month())
            except Exception:
                self.logger.exception("Monthly expense run failed")

    # -- core --------------------------------------------------------------

    def run_once(self, month: str, *, escalate: bool = True) -> dict[str, Any]:
        """Compile and publish the expense report for ``month`` (YYYY-MM).

        ``escalate`` controls whether uncategorized transactions trigger
        request_manual_accounting. It is set False when that agent reruns us
        after a manual accounting pass, to avoid a re-escalation loop.
        """
        self.logger.info("Compiling monthly expenses for %s", month)
        # Reload learned categories so reruns pick up manual corrections.
        self.finance_config = load_finance_config()
        self.keyword_maps = cat.load_company_keywords(self.finance_config)
        start, end = transactions.month_range(month)

        txns = self._gather_outflows(start, end)
        grouped, grand_total = self._categorize(txns)
        report = self._build_report(month, grouped, grand_total)

        page_id = self._publish_notion(month, report)
        self._publish_slack(month, grand_total, page_id)

        uncategorized = [
            t for t in txns if cat.classify_budget(t, self.keyword_maps) == cat.UNCATEGORIZED
        ]
        if uncategorized and escalate:
            self.logger.info(
                "%d uncategorized txns — starting request_manual_accounting", len(uncategorized)
            )
            self._dispatch_manual_accounting(month, uncategorized)

        return {
            "month": month,
            "transaction_count": len(txns),
            "grand_total": grand_total,
            "uncategorized_count": len(uncategorized),
            "notion_page_id": page_id,
            "report": report,
        }

    def _gather_outflows(self, start: str, end: str) -> list[dict]:
        from company_brain.runtime import get_runtime

        from .mercury.bank_transaction import BankTransactionAgent
        from .mercury.card_spend import MercuryCardSpendAgent
        from .ramp.card_spend import RampCardSpendAgent

        runtime = get_runtime()
        txns: list[dict] = []

        bank = runtime.run(
            BankTransactionAgent,
            self.config,
            start=start,
            end=end,
            include_inbound=False,
            include_outbound=True,
        )
        txns.extend(bank.get("transactions", []))

        card = runtime.run(MercuryCardSpendAgent, self.config, start=start, end=end)
        txns.extend(card.get("transactions", []))

        try:
            ramp = runtime.run(RampCardSpendAgent, self.config, start=start, end=end)
            txns.extend(ramp.get("transactions", []))
        except Exception:
            self.logger.exception("Ramp card spend unavailable; continuing with Mercury only")

        return [t for t in txns if t.get("amount", 0) < 0]

    def _categorize(self, txns: list[dict]) -> tuple[dict[str, list[dict]], float]:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for t in txns:
            grouped[cat.classify_budget(t, self.keyword_maps)].append(t)
        grand_total = sum(abs(t["amount"]) for t in txns)
        return dict(grouped), grand_total

    def _build_report(self, month: str, grouped: dict[str, list[dict]], grand_total: float) -> str:
        label = transactions.month_label(month)
        lines = [f"# {label} Expenses", ""]
        lines.append(f"*Generated: {datetime.now():%Y-%m-%d %H:%M}*")
        lines.append(f"*Total outbound spend: {transactions.fmt_money(grand_total)}*")
        lines.append("")
        ordered = sorted(
            grouped.items(),
            key=lambda kv: (kv[0] == cat.UNCATEGORIZED, -sum(abs(t["amount"]) for t in kv[1])),
        )
        for subcat, items in ordered:
            subtotal = sum(abs(t["amount"]) for t in items)
            lines.append(f"## {subcat} — {transactions.fmt_money(subtotal)}")
            lines.append("")
            by_vendor: dict[str, float] = defaultdict(float)
            for t in items:
                by_vendor[t.get("name") or "Unknown"] += abs(t["amount"])
            for vendor, amt in sorted(by_vendor.items(), key=lambda x: -x[1])[:25]:
                lines.append(f"- {vendor}: {transactions.fmt_money(amt)}")
            lines.append("")
        return "\n".join(lines)

    def _publish_notion(self, month: str, report: str) -> str | None:
        # Each month gets its own page under "Monthly Expense Reports", overwritten
        # in place on re-run.
        notion_pages.ensure_page(PARENT_KEY, PARENT_TERMS, "Monthly Expense Reports")
        label = transactions.month_label(month)
        child_key = f"monthly_expense_{month}"
        page_id = notion_pages.ensure_page(
            child_key,
            [f"{label} Expenses"],
            f"{label} Expenses",
            parent_key=PARENT_KEY,
        )
        notion_pages.update_page_body(page_id, report)
        return page_id

    def _publish_slack(self, month: str, grand_total: float, page_id: str | None) -> None:
        from company_brain.notify import ACTIONABLE, INFO, Signal, from_finance_config

        label = transactions.month_label(month)
        # Detect everything, notify selectively: ping only when there was spend.
        severity = ACTIONABLE if grand_total > 0 else INFO
        try:
            from_finance_config(self.finance_config).emit(
                Signal(
                    text=(
                        f"{label} expense report ready — "
                        f"total outbound {transactions.fmt_money(grand_total)}."
                    ),
                    severity=severity,
                    link_label=f"{label} Expenses",
                    link_url=notion_pages.page_url(page_id) if page_id else None,
                )
            )
        except Exception:
            self.logger.exception("Slack notification failed")

    def _dispatch_manual_accounting(self, month: str, uncategorized: list[dict]) -> None:
        from company_brain.runtime import get_runtime

        from .request_manual_accounting import RequestManualAccountingAgent

        get_runtime().run(
            RequestManualAccountingAgent,
            self.config,
            source_agent=self.name,
            context={"period": month, "kind": "monthly"},
            uncategorized=uncategorized,
        )

    @staticmethod
    def _next_run_time(now: datetime) -> datetime:
        """Next occurrence of the 1st of a month at RUN_TIME."""
        candidate = now.replace(
            day=RUN_DAY, hour=RUN_TIME.hour, minute=RUN_TIME.minute, second=0, microsecond=0
        )
        if now >= candidate:
            # advance to the 1st of next month
            year = now.year + (1 if now.month == 12 else 0)
            month = 1 if now.month == 12 else now.month + 1
            candidate = candidate.replace(year=year, month=month)
        return candidate
