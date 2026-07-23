"""Subscription Audit Agent (ephemeral).

Started on command by quarterly_calculation. Pulls recurring expense
transactions over the past 3 months (via the Mercury bank, Mercury card, and
Ramp card specialists), cross-verifies pricing via online search, flags
overlapping services, updates the Notion "Company Subscriptions" database, and
posts a service-overlap report to Slack #finance with a link.

SDK: Anthropic Claude Agent SDK. Recurring-charge detection is deterministic;
pricing verification uses ``company_brain.web_search`` (default ``lsearch``,
Claude ``WebSearch`` fallback). Falls back to a deterministic report if the
SDK is unavailable.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.config import AppConfig

from .shared import notion_pages, transactions
from .shared.config import load_finance_config

SUBSCRIPTIONS_KEY = "subscription"
SUBSCRIPTIONS_TERMS = ["Subscriptions"]


def _current_quarter() -> str:
    today = date.today()
    return f"{today.year}-Q{(today.month - 1) // 3 + 1}"


_RESULT_START = "<<<AUDIT_MD>>>"
_RESULT_END = "<<<END_AUDIT_MD>>>"


class SubscriptionAuditAgent(BaseAgent):
    """Detect recurring subscriptions, verify pricing, flag overlaps.

    Update agent: the Company Subscriptions page is overwritten with the current
    audit each run.
    """

    name = "finance_subscription_audit"
    WRITE_MODE = "update"

    def __init__(self, config: AppConfig, model: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.model = model
        self.finance_config = load_finance_config()

    def should_run(self, *, quarter: str | None = None, force: bool = False, **kwargs: Any) -> bool:
        """Cost gate: audit a given quarter at most once (dedup re-fires).

        Ad-hoc runs (no ``quarter``) gate on the current quarter so repeated
        invocations stand down; pass ``force=True`` to bypass explicitly.
        """
        if force:
            return True
        from company_brain.agents.gates import changed_since

        effective = quarter or _current_quarter()
        return changed_since(f"subscription_audit:{effective}", effective)

    def verify(self, output: Any, **kwargs: Any):
        """Triage: no recurring vendors is 'noise' (suppress the ping)."""
        from company_brain.agents.result import AgentResult

        n = (output or {}).get("recurring_count", 0)
        return AgentResult(output=output, status="ok" if n else "noise")

    def run(
        self, *, quarter: str | None = None, months_back: int = 3, **kwargs: Any
    ) -> dict[str, Any]:
        self.logger.info("Auditing subscriptions over the past %d months", months_back)
        recurring = self._detect_recurring(self._recent_months(months_back))
        self.logger.info("Detected %d recurring vendors", len(recurring))

        report = self._build_report(recurring)

        page_id = notion_pages.ensure_page(SUBSCRIPTIONS_KEY, SUBSCRIPTIONS_TERMS, "Subscriptions")
        if page_id:
            notion_pages.update_page_body(page_id, report)

        self._post_slack(recurring, page_id)
        return {
            "recurring_count": len(recurring),
            "subscriptions_page_id": page_id,
            "report": report,
        }

    # -- detection ---------------------------------------------------------

    def _recent_months(self, months_back: int) -> list[str]:
        today = date.today()
        months: list[str] = []
        y, m = today.year, today.month
        for _ in range(months_back):
            m -= 1
            if m == 0:
                m = 12
                y -= 1
            months.append(f"{y}-{m:02d}")
        return months

    def _detect_recurring(self, months: list[str]) -> list[dict]:
        from company_brain.runtime import get_runtime

        from .mercury.bank_transaction import BankTransactionAgent
        from .mercury.card_spend import MercuryCardSpendAgent
        from .ramp.card_spend import RampCardSpendAgent

        runtime = get_runtime()
        all_txns: list[dict] = []
        for month in months:
            start, end = transactions.month_range(month)
            all_txns.extend(
                runtime.run(
                    BankTransactionAgent,
                    self.config,
                    start=start,
                    end=end,
                    include_inbound=False,
                    include_outbound=True,
                ).get("transactions", [])
            )
            all_txns.extend(
                runtime.run(
                    MercuryCardSpendAgent,
                    self.config,
                    start=start,
                    end=end,
                ).get("transactions", [])
            )
            try:
                all_txns.extend(
                    runtime.run(
                        RampCardSpendAgent,
                        self.config,
                        start=start,
                        end=end,
                    ).get("transactions", [])
                )
            except Exception:
                self.logger.exception("Ramp unavailable for %s during subscription audit", month)

        by_vendor: dict[str, list[dict]] = defaultdict(list)
        for t in all_txns:
            if t.get("amount", 0) < 0 and t.get("name"):
                by_vendor[t["name"]].append(t)

        recurring: list[dict] = []
        for vendor, charges in by_vendor.items():
            active_months = sorted({c["date"][:7] for c in charges if c.get("date")})
            if len(active_months) < 2:
                continue
            amounts = [abs(c["amount"]) for c in charges]
            recurring.append(
                {
                    "name": vendor,
                    "charge_count": len(charges),
                    "months_active": len(active_months),
                    "avg_amount": round(sum(amounts) / len(amounts), 2) if amounts else 0,
                    "total": round(sum(amounts), 2),
                    "sources": ", ".join(sorted({c.get("source", "") for c in charges})),
                }
            )
        return sorted(recurring, key=lambda x: -x["total"])

    # -- reporting ---------------------------------------------------------

    def _build_report(self, recurring: list[dict]) -> str:
        try:
            body = asyncio.run(self._build_with_claude(recurring))
            if body.strip():
                return body
        except ImportError:
            self.logger.warning("claude-agent-sdk not installed — using deterministic audit")
        except Exception:
            self.logger.exception("Claude subscription audit failed — using deterministic fallback")
        return self._deterministic_report(recurring)

    async def _build_with_claude(self, recurring: list[dict]) -> str:
        from claude_agent_sdk import ClaudeAgentOptions

        from company_brain import web_search as ws
        from company_brain.llm import claude as llm_claude
        from company_brain.llm.tracking import iter_claude_query

        vendor_block = "\n".join(
            f"- {v['name']}: {v['charge_count']} charges over {v['months_active']} months, "
            f"avg {transactions.fmt_money(v['avg_amount'])}, "
            f"total {transactions.fmt_money(v['total'])} "
            f"(source: {v['sources']})"
            for v in recurring
        )

        pricing_context = ""
        allow_tools: list[str] = []
        if recurring and ws.resolve_backend() == "lsearch":
            names = [str(v["name"]) for v in recurring[:12]]
            query = "public pricing " + ", ".join(names)
            gathered = ws.gather_markdown(query, limit=8, with_content=False, cleanup=True)
            if gathered.get("ok") and gathered.get("markdown"):
                pricing_context = str(gathered["markdown"])
            else:
                allow_tools = ["WebSearch"]
        else:
            allow_tools = ["WebSearch"]

        if pricing_context:
            prompt = f"""You are a subscription auditing agent. Below is pre-computed
recurring-charge data and gathered public pricing search results. Verify each
vendor's public pricing from the gathered data, then flag overlapping services
and suggest consolidations.

RECURRING VENDORS:
{vendor_block or "(none detected)"}

GATHERED PRICING SEARCH:
{pricing_context}

Produce a markdown report titled "# Subscription Audit" with:
- a summary table (vendor, avg charge, annual estimate, verified price, notes)
- a "Service Overlap" section grouping vendors with overlapping functionality

Wrap the entire markdown report between {_RESULT_START} and {_RESULT_END}."""
        else:
            prompt = f"""You are a subscription auditing agent. Below is pre-computed
recurring-charge data. Use web search to verify each vendor's public pricing,
then flag overlapping services and suggest consolidations.

RECURRING VENDORS:
{vendor_block or "(none detected)"}

Produce a markdown report titled "# Subscription Audit" with:
- a summary table (vendor, avg charge, annual estimate, verified price, notes)
- a "Service Overlap" section grouping vendors with overlapping functionality

Wrap the entire markdown report between {_RESULT_START} and {_RESULT_END}."""

        options = ClaudeAgentOptions(
            allowed_tools=allow_tools,
            env=llm_claude.options_env(),
            **llm_claude.model_kwargs(self.model, agent_name="subscription_audit"),
        )
        out: list[str] = []
        async for message in iter_claude_query(
            "subscription_audit",
            prompt=prompt,
            options=options,
        ):
            result = getattr(message, "result", None)
            if isinstance(result, str):
                out.append(result)
        raw = "\n".join(out)
        s, e = raw.rfind(_RESULT_START), raw.rfind(_RESULT_END)
        if s != -1 and e > s:
            return raw[s + len(_RESULT_START) : e].strip()
        return raw

    @staticmethod
    def _deterministic_report(recurring: list[dict]) -> str:
        lines = [
            "# Subscription Audit",
            "",
            f"*Generated deterministically; {len(recurring)} recurring vendors.*",
            "",
        ]
        lines.append("| Vendor | Charges | Months | Avg | Total | Source |")
        lines.append("|---|---|---|---|---|---|")
        for v in recurring:
            lines.append(
                f"| {v['name']} | {v['charge_count']} | {v['months_active']} | "
                f"{transactions.fmt_money(v['avg_amount'])} | "
                f"{transactions.fmt_money(v['total'])} | {v['sources']} |"
            )
        lines.append("")
        return "\n".join(lines)

    def _post_slack(self, recurring: list[dict], page_id: str | None) -> None:
        from company_brain.notify import ACTIONABLE, INFO, Signal, from_finance_config

        total = sum(v["total"] for v in recurring)
        # Notify selectively: only ping when there are recurring vendors to review.
        severity = ACTIONABLE if recurring else INFO
        try:
            from_finance_config(self.finance_config).emit(
                Signal(
                    text=(
                        f"Subscription audit complete: {len(recurring)} recurring vendors, "
                        f"~{transactions.fmt_money(total)} over the review window."
                    ),
                    severity=severity,
                    link_label="Subscriptions",
                    link_url=notion_pages.page_url(page_id) if page_id else None,
                )
            )
        except Exception:
            self.logger.exception("Slack notification failed")
