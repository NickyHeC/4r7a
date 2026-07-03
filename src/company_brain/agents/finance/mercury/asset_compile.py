"""Asset Compile Agent — snapshot total Mercury assets at a point in time.

Compiles total assets from Mercury bank (checking/savings) and Treasury
(money-market) accounts for a given date. Per spec, the credit card balance is
NOT included. For past periods it prefers month-end statement balances; for the
current period it uses live balances.

SDK: Neither (deterministic Python via the Mercury CLI wrapper). No LLM is
needed — this is a pure data aggregation, so we keep it transparent and fast.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.config import AppConfig

from . import mercury_client as mc

AGENT_KEY = "asset_compile"


class AssetCompileAgent(BaseAgent):
    """Snapshot Mercury bank + treasury balances for a target date."""

    name = "finance_asset_compile"
    WRITE_MODE = "append"

    def __init__(self, config: AppConfig, *, publish: bool = True, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.publish = publish

    def run(
        self, *, month: str | None = None, quarter: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Compile assets for a month-end, quarter-end, or current date.

        Returns a dict with bank/treasury totals, per-account detail, and a
        markdown report string. When ``publish`` is set, the snapshot is appended
        (newest on top) to the "Total Assets" wiki page and synced to Notion.
        """
        if month:
            target = mc.month_end(month)
            label = f"{month} Month-End"
        elif quarter:
            target = mc.quarter_end(quarter)
            label = quarter
        else:
            quarter = mc.current_quarter()
            target = mc.quarter_end(quarter)
            label = quarter

        is_historical = target < date.today()
        self.logger.info("Compiling assets for %s (target %s)", label, target)

        bank = self._collect_bank(target, is_historical)
        treasury = self._collect_treasury()

        bank_total = sum(b["balance"] for b in bank)
        treasury_total = sum(t["balance"] for t in treasury)
        total = bank_total + treasury_total

        from company_brain.wiki.publish import format_append_section

        body = self._build_report_body(
            label, target, bank, treasury, bank_total, treasury_total, total,
        )
        report = format_append_section(
            label,
            body,
            trigger="asset_compile agent",
            why=f"snapshot for {label} (as-of {target})",
        )

        page_id = None
        if self.publish:
            from company_brain.wiki.publish import write_wiki_page

            page_id = write_wiki_page(
                "finance/total-asset.md",
                "Total Assets",
                report,
                mode=self.WRITE_MODE,
                section="finance",
                type_="report",
            )

        return {
            "label": label,
            "target_date": str(target),
            "bank_total": bank_total,
            "treasury_total": treasury_total,
            "total_assets": total,
            "bank": bank,
            "treasury": treasury,
            "report": report,
            "notion_page_id": page_id,
        }

    def _collect_bank(self, target: date, is_historical: bool) -> list[dict]:
        bank: list[dict] = []
        for acct in mc.list_accounts():
            if is_historical:
                statements = mc.list_account_statements(acct["id"])
                balance, source = self._bank_balance_at(acct, statements, target)
            else:
                balance, source = acct.get("currentBalance", 0.0), "live balance"
            if acct.get("status") != "active" and not balance:
                continue
            bank.append(
                {
                    "name": acct.get("name", ""),
                    "nickname": acct.get("nickname", ""),
                    "kind": acct.get("kind", ""),
                    "status": acct.get("status", ""),
                    "balance": balance,
                    "source": source,
                }
            )
        return bank

    def _collect_treasury(self) -> list[dict]:
        treasury: list[dict] = []
        for t in mc.list_treasury_accounts():
            treasury.append(
                {
                    "balance": t.get("currentBalance", 0.0),
                    "source": "live balance (no historical API)",
                }
            )
        return treasury

    @staticmethod
    def _bank_balance_at(account: dict, statements: list[dict], target: date) -> tuple[float, str]:
        target_ym = target.strftime("%Y-%m")
        for s in statements:
            end_date = (s.get("endDate") or "")[:10]
            if end_date[:7] == target_ym:
                return s.get("endingBalance", 0.0), f"statement {end_date}"
        return account.get("currentBalance", 0.0), "live balance"

    @staticmethod
    def _build_report_body(label, target, bank, treasury, bank_total, treasury_total, total) -> str:
        lines = [f"*As of {target}*", ""]
        lines.append("### Mercury Bank Accounts")
        lines.append("")
        for b in sorted(bank, key=lambda x: -x["balance"]):
            nick = f" — {b['nickname']}" if b.get("nickname") else ""
            lines.append(f"- {b['name']}{nick}: {mc.fmt_money(b['balance'])} ({b['kind']})")
        lines.append("")
        lines.append(f"**Mercury Bank Total: {mc.fmt_money(bank_total)}**")
        lines.append("")
        if treasury:
            lines.append("### Mercury Treasury")
            lines.append("")
            for t in treasury:
                lines.append(f"- Treasury Account: {mc.fmt_money(t['balance'])}")
            lines.append("")
            lines.append(f"**Mercury Treasury Total: {mc.fmt_money(treasury_total)}**")
            lines.append("")
        lines.append("---")
        lines.append(f"**Total Assets (Bank + Treasury): {mc.fmt_money(total)}**")
        lines.append("")
        return "\n".join(lines)
