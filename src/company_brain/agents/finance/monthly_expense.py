"""Monthly Expense Manager.

A persistent department manager. On the 1st of each month at 08:00 it dispatches
the transaction specialists (Mercury bank, Mercury card, Ramp card) for the
previous month, sorts outbound spend into budget categories, posts the compiled
report to Slack #finance, and writes the month's wiki expense report before its
Notion mirror. Idles between runs.

SDK: Anthropic Claude Agent SDK (optional narrative polish of the report) layered
on deterministic categorization. Orchestration (dispatch + schedule) is plain
asyncio, mirroring the engineering github_manager.

If any transactions are uncategorized, it starts request_manual_accounting to
solicit human help before the report is considered final.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.scheduling.calendar import (
    calendar_run_for_month,
    next_calendar_run,
    parse_hhmm,
)
from company_brain.config import AppConfig

from .shared import categories as cat
from .shared import notion_pages, transactions
from .shared.config import load_finance_config

PARENT_KEY = "monthly_expense_reports"
PARENT_TERMS = ["Monthly Expense Reports", "Monthly Expense Report"]
COMPLETED_KEY_PREFIX = "finance_monthly_expense:completed:"


class MonthlyExpenseManager(BaseAgent):
    """Persistent manager that compiles a monthly expense report.

    Update agent: each month gets its own page under "Monthly Expense Reports",
    overwritten in place on re-run.
    """

    name = "finance_monthly_expense"
    track_duration = False
    WRITE_MODE = "update"
    fleet_exempt = True

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.finance_config = load_finance_config()
        self.keyword_maps = cat.load_company_keywords(self.finance_config)
        self._state = StateStore()

    # -- lifecycle ---------------------------------------------------------

    def run(
        self,
        *,
        once: bool = False,
        month: str | None = None,
        escalate: bool = True,
        **kwargs: Any,
    ) -> Any:
        """Start the persistent loop, or run a single month when ``once``."""
        if once:
            return self.run_once(month or transactions.previous_month(), escalate=escalate)
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        self.logger.info("Monthly expense manager starting persistent loop")
        while True:
            now = datetime.now()
            month = transactions.previous_month()
            if self._catch_up_due(now) and not self._state.get(f"{COMPLETED_KEY_PREFIX}{month}"):
                try:
                    result = self.run_once(month)
                    if result.get("reason") == "fleet_paused":
                        await asyncio.sleep(300)
                        continue
                except Exception:
                    self.logger.exception("Monthly expense catch-up failed")
                    await asyncio.sleep(300)
                    continue
            nxt = self._next_run_time(now)
            wait = (nxt - now).total_seconds()
            self.logger.info("Next monthly run at %s (sleep %.0fs)", nxt.isoformat(), wait)
            await asyncio.sleep(wait)
            while True:
                try:
                    result = self.run_once(transactions.previous_month())
                    if result.get("reason") != "fleet_paused":
                        break
                except Exception:
                    self.logger.exception("Monthly expense run failed")
                    break
                await asyncio.sleep(300)

    # -- core --------------------------------------------------------------

    def run_once(self, month: str, *, escalate: bool = True) -> dict[str, Any]:
        """Run one report inside a fleet dispatch slot."""
        from company_brain.runtime.fleet_gate import dispatch_slot

        with dispatch_slot(self.name) as allowed:
            if not allowed:
                return {"status": "skipped", "reason": "fleet_paused", "month": month}
            result = self._run_report(month, escalate=escalate)
            self._state.set(f"{COMPLETED_KEY_PREFIX}{month}", datetime.now().isoformat())
            return result

    def _run_report(self, month: str, *, escalate: bool = True) -> dict[str, Any]:
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

        wiki_path = self._publish_report(month, report)
        self._publish_slack(month, grand_total, wiki_path)

        # Snapshot total assets for the reported month-end (≈ start of the new
        # month, which is when this manager runs). Best-effort; Mercury may be
        # unavailable in some installs.
        assets = self._dispatch_asset_snapshot(month)

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
            "wiki_path": wiki_path,
            "total_assets": (assets or {}).get("total_assets"),
            "report": report,
        }

    def _dispatch_asset_snapshot(self, month: str) -> dict[str, Any] | None:
        from company_brain.runtime import get_runtime

        from .mercury.asset_compile import AssetCompileAgent

        try:
            return get_runtime().run(AssetCompileAgent, self.config, month=month)
        except Exception:
            self.logger.exception("Asset snapshot unavailable; continuing without it")
            return None

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
            ramp = runtime.run(
                RampCardSpendAgent,
                self.config,
                start=start,
                end=end,
                force=True,
            )
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

    def _publish_report(self, month: str, report: str) -> str:
        # Each month gets its own page under "Monthly Expense Reports", overwritten
        # in place on re-run.
        notion_pages.ensure_page(PARENT_KEY, PARENT_TERMS, "Monthly Expense Reports")
        label = transactions.month_label(month)
        child_key = f"monthly_expense_{month}"
        wiki_path = notion_pages.ensure_page(
            child_key,
            [f"{label} Expenses"],
            f"{label} Expenses",
        )
        notion_pages.update_page_body(wiki_path, report)
        return wiki_path

    def _publish_slack(self, month: str, grand_total: float, wiki_path: str) -> None:
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
                    link_url=notion_pages.page_url(wiki_path),
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
        """Next configured monthly expense run."""
        schedule = (load_finance_config().get("schedules") or {}).get("monthly_expense") or {}
        return next_calendar_run(
            now,
            day=int(schedule.get("day_of_month") or 1),
            at=parse_hhmm(str(schedule.get("time") or "08:00")),
        )

    @staticmethod
    def _catch_up_due(now: datetime) -> bool:
        schedule = (load_finance_config().get("schedules") or {}).get("monthly_expense") or {}
        deadline = calendar_run_for_month(
            now,
            day=int(schedule.get("day_of_month") or 1),
            at=parse_hhmm(str(schedule.get("time") or "08:00")),
        )
        return now >= deadline
