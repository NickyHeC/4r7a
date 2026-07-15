"""LLM Expense Report — monthly agent spend snapshot (MD-first).

SDK: Neither (deterministic rollup from StateStore usage + duration + verify).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.admin.llm_ops_config import month_title, previous_month
from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.config import AppConfig
from company_brain.llm.budget import budget_status, usage_for_month
from company_brain.llm.duration import duration_stats, list_duration_agents
from company_brain.wiki.publish import UPDATE, write_wiki_page

WIKI_PATH_TMPL = "admin/llm-expense/{month}.md"
TITLE_TMPL = "{label} Agent Expenses"


class LlmExpenseReportAgent(BaseAgent):
    """Write ``admin/llm-expense/{YYYY-MM}.md`` from the monthly usage ledger."""

    name = "llm_expense_report"
    WRITE_MODE = UPDATE

    def __init__(self, config: AppConfig, store: StateStore | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._store = store or StateStore()

    def run(self, *, month: str | None = None, sync: bool = True, **kwargs: Any) -> dict[str, Any]:
        month = month or previous_month()
        usage = usage_for_month(month, store=self._store)
        status = budget_status(store=self._store)
        body = self._render(month, usage, status)
        title = TITLE_TMPL.format(label=month_title(month))
        path = WIKI_PATH_TMPL.format(month=month)
        write_wiki_page(
            path,
            title,
            body,
            mode=UPDATE,
            section="admin",
            type_="report",
            sync=sync,
            sync_label="admin_only",
            extra_frontmatter={"month": month, "report": "llm_expense"},
        )
        return {
            "month": month,
            "path": path,
            "spent_usd": usage.get("estimated_usd") or 0,
            "agents": len(usage.get("agents") or {}),
        }

    def _render(self, month: str, usage: dict[str, Any], status: dict[str, Any]) -> str:
        label = month_title(month)
        cats = usage.get("categories") or {}
        agents = usage.get("agents") or {}
        lines = [
            f"# {label} Agent Expenses",
            "",
            f"**Month:** {month}",
            f"**Estimated spend:** ${float(usage.get('estimated_usd') or 0):.2f}",
            f"**Tokens:** {int(usage.get('input_tokens') or 0):,} in / "
            f"{int(usage.get('output_tokens') or 0):,} out"
            f" / cache_read {int(usage.get('cache_read_tokens') or 0):,}"
            f" / reasoning {int(usage.get('reasoning_tokens') or 0):,}",
            f"**Unknown-model calls:** {int(usage.get('unknown_model_calls') or 0)}",
            "",
            "## By category",
            "",
            "| Category | USD | Input | Output | Cache read | Reasoning |",
            "|----------|-----|-------|--------|------------|-----------|",
        ]
        for name in sorted(cats):
            block = cats[name]
            lines.append(
                f"| `{name}` | ${float(block.get('estimated_usd') or 0):.2f} | "
                f"{int(block.get('input_tokens') or 0):,} | "
                f"{int(block.get('output_tokens') or 0):,} | "
                f"{int(block.get('cache_read_tokens') or 0):,} | "
                f"{int(block.get('reasoning_tokens') or 0):,} |"
            )
        if not cats:
            lines.append("| — | $0.00 | 0 | 0 | 0 | 0 |")

        lines.extend(
            [
                "",
                "## By agent",
                "",
                "| Agent | USD | Verify ok/rework/noise | Attributed managers |",
                "|-------|-----|------------------------|---------------------|",
            ]
        )
        for name in sorted(agents):
            block = agents[name]
            verify = block.get("verify") or {}
            mgrs = block.get("managers") or {}
            mgr_bits = (
                ", ".join(
                    f"`{m}` ${float(b.get('estimated_usd') or 0):.2f}"
                    for m, b in sorted(mgrs.items())
                )
                or "—"
            )
            lines.append(
                f"| `{name}` | ${float(block.get('estimated_usd') or 0):.2f} | "
                f"{int(verify.get('ok') or 0)}/"
                f"{int(verify.get('rework') or 0)}/"
                f"{int(verify.get('noise') or 0)} | {mgr_bits} |"
            )
        if not agents:
            lines.append("| — | $0.00 | 0/0/0 | — |")

        lines.extend(
            [
                "",
                "## Specialist duration (rolling)",
                "",
                "| Agent | n | p50 min | p95 min |",
                "|-------|---|---------|---------|",
            ]
        )
        for agent in list_duration_agents(store=self._store):
            stats = duration_stats(agent, store=self._store)
            lines.append(
                f"| `{agent}` | {stats['count']} | "
                f"{stats['p50_ms'] / 60_000:.2f} | {stats['p95_ms'] / 60_000:.2f} |"
            )
        if not list_duration_agents(store=self._store):
            lines.append("| — | 0 | — | — |")

        lines.extend(
            [
                "",
                "## Budget status (current month)",
                "",
                f"- Enabled: {status.get('enabled')}",
                f"- Spent: ${float(status.get('spent_usd') or 0):.2f} / "
                f"${float(status.get('limit_usd') or 0):.2f} "
                f"({float(status.get('percent_used') or 0):.1f}%)",
                f"- Runtime / builder: ${float(status.get('runtime_usd') or 0):.2f} / "
                f"${float(status.get('builder_usd') or 0):.2f}",
                "",
            ]
        )
        return "\n".join(lines)
