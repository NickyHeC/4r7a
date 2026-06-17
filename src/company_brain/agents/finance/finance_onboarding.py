"""Finance Onboarding Agent.

Runs ONCE when the finance department (Mercury + Ramp) is first connected.
Backfills history by running the monthly_expense and quarterly_calculation
managers for every month and quarter that has pre-existing transactions, so the
Notion pages start fully populated.

To avoid flooding Slack/Notion with manual-accounting requests across many
historical periods, the backfill runs with escalation disabled (escalate=False);
ongoing live runs still escalate normally.

When the backfill is done it hands off to the department's persistent managers:
it starts both `monthly_expense` and `quarterly_calculation`, whose loops idle
until their next scheduled times (the 1st of the month / the 5th of the quarter)
so steady-state runs continue automatically.

SDK: Neither (orchestration only) — it sequences the existing managers.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.config import AppConfig

from .mercury import mercury_client as mc
from .shared import transactions
from .shared.config import load_finance_config


class FinanceOnboardingAgent(BaseAgent):
    """One-time backfill of monthly and quarterly reports over all history."""

    name = "finance_onboarding"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.finance_config = load_finance_config()

    def run(self, *, start_month: str | None = None, start_managers: bool = True,
            **kwargs: Any) -> dict[str, Any]:
        start_month = start_month or self._detect_start_month()
        if not start_month:
            self.logger.warning("Could not determine a start month; nothing to backfill")
            return {"status": "no_data"}

        months = self._months_through_last_complete(start_month)
        quarters = self._quarters_for_months(months)
        self.logger.info("Onboarding backfill: %d months, %d quarters (from %s)",
                         len(months), len(quarters), start_month)

        from .monthly_expense import MonthlyExpenseManager
        from .quarterly_calculation import QuarterlyCalculationManager

        monthly = MonthlyExpenseManager(self.config)
        quarterly = QuarterlyCalculationManager(self.config)

        for m in months:
            try:
                monthly.run_once(m, escalate=False)
            except Exception:
                self.logger.exception("Backfill monthly run failed for %s", m)

        for q in quarters:
            try:
                quarterly.run_once(q, escalate=False)
            except Exception:
                self.logger.exception("Backfill quarterly run failed for %s", q)

        if start_managers:
            self._start_managers()

        return {"status": "done", "months": months, "quarters": quarters}

    def _start_managers(self) -> None:
        """Hand off to the persistent finance managers (run at their next schedules)."""
        from company_brain.runtime import get_runtime

        from .monthly_expense import MonthlyExpenseManager
        from .quarterly_calculation import QuarterlyCalculationManager

        self.logger.info(
            "Backfill complete — starting monthly_expense + quarterly_calculation "
            "(idle until the 1st of the month / 5th of the quarter)"
        )
        runtime = get_runtime()
        for manager_cls in (MonthlyExpenseManager, QuarterlyCalculationManager):
            try:
                runtime.start(manager_cls, self.config)
            except Exception:
                self.logger.exception(
                    "Failed to start %s", getattr(manager_cls, "name", manager_cls.__name__)
                )

    # -- period enumeration -----------------------------------------------

    def _detect_start_month(self) -> str | None:
        """Earliest month with a Mercury transaction (config override first)."""
        configured = (self.finance_config.get("onboarding") or {}).get("start_month")
        if configured:
            return configured
        try:
            accounts = [a for a in mc.list_accounts() if a.get("status") == "active"]
            dates = [
                mc.txn_date(t)
                for t in mc.list_all_transactions(accounts)
                if mc.txn_date(t)
            ]
            if dates:
                return min(dates)[:7]
        except Exception:
            self.logger.exception("Failed to detect earliest transaction month")
        return None

    @staticmethod
    def _months_through_last_complete(start_month: str) -> list[str]:
        """All months from start_month through the last fully-completed month."""
        today = date.today()
        last = transactions.previous_month(today)  # last complete month
        months: list[str] = []
        y, m = int(start_month[:4]), int(start_month[5:7])
        ly, lm = int(last[:4]), int(last[5:7])
        while (y, m) <= (ly, lm):
            months.append(f"{y}-{m:02d}")
            m += 1
            if m == 13:
                m = 1
                y += 1
        return months

    @staticmethod
    def _quarters_for_months(months: list[str]) -> list[str]:
        quarters: list[str] = []
        for m in months:
            q = f"{m[:4]}-Q{(int(m[5:7]) - 1) // 3 + 1}"
            if q not in quarters:
                quarters.append(q)
        return quarters
