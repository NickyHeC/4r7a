"""Admin maintain — monthly drift review + coding-session request.

SDK: Neither (deterministic). Does not auto-edit yaml or open PRs.
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.admin.llm_ops_config import llm_ops_config, month_title, previous_month
from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.config import AppConfig
from company_brain.llm.admin_notify import wiki_admin_notifier
from company_brain.llm.budget import budget_status, usage_for_month
from company_brain.llm.duration import duration_stats, list_duration_agents
from company_brain.notify import ACTIONABLE, INFO, Signal
from company_brain.wiki.publish import UPDATE, write_wiki_page

RUNTIME_PATH = "admin/agent-runtime.md"
RUNTIME_TITLE = "Agent Runtime"
MAINTAIN_PATH_TMPL = "admin/maintain/{month}.md"


class AdminMaintainAgent(BaseAgent):
    """Refresh agent-runtime wiki + write monthly maintain page; notify on drift."""

    name = "admin_maintain"
    WRITE_MODE = UPDATE

    def __init__(self, config: AppConfig, store: StateStore | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._store = store or StateStore()

    def run(self, *, month: str | None = None, sync: bool = True, **kwargs: Any) -> dict[str, Any]:
        month = month or previous_month()
        cfg = llm_ops_config()
        usage = usage_for_month(month, store=self._store)
        status = budget_status(store=self._store)
        drifts = self._collect_drifts(cfg, usage, status)
        self._write_runtime_page(cfg, sync=sync)
        path = MAINTAIN_PATH_TMPL.format(month=month)
        body = self._render_maintain(month, drifts, status)
        write_wiki_page(
            path,
            f"Maintain — {month}",
            body,
            mode=UPDATE,
            section="admin",
            type_="review",
            sync=sync,
            sync_label="admin_only",
            extra_frontmatter={"month": month, "report": "admin_maintain"},
        )
        notified = self._notify(month, drifts, status)
        return {
            "month": month,
            "path": path,
            "runtime_path": RUNTIME_PATH,
            "drifts": drifts,
            "notified": notified,
        }

    def _collect_drifts(
        self,
        cfg: dict[str, Any],
        usage: dict[str, Any],
        status: dict[str, Any],
    ) -> list[dict[str, Any]]:
        drifts: list[dict[str, Any]] = []
        drift_ratio = float(cfg.get("drift_ratio") or 0.5)
        fail_rate_cap = float(cfg.get("verify_fail_rate") or 0.3)
        min_verify = int(cfg.get("min_verify_samples") or 5)
        fallbacks = dict(cfg.get("estimated_minutes") or {})

        if status.get("over_budget"):
            drifts.append(
                {
                    "kind": "budget",
                    "severity": "alert",
                    "detail": (
                        f"Monthly LLM budget exhausted "
                        f"(${status['spent_usd']:.2f} / ${status['limit_usd']:.2f})"
                    ),
                }
            )
        elif status.get("near_limit"):
            drifts.append(
                {
                    "kind": "budget",
                    "severity": "actionable",
                    "detail": (
                        f"LLM budget near limit "
                        f"({status['percent_used']}% — "
                        f"${status['spent_usd']:.2f} / ${status['limit_usd']:.2f})"
                    ),
                }
            )

        for agent in list_duration_agents(store=self._store):
            stats = duration_stats(agent, store=self._store)
            if stats["count"] < 5:
                continue
            fallback = int(fallbacks.get(agent) or 0)
            if fallback <= 0:
                continue
            measured = max(int((stats["p95_ms"] + 59_999) // 60_000), 1)
            delta = abs(measured - fallback) / float(fallback)
            if delta >= drift_ratio:
                drifts.append(
                    {
                        "kind": "duration",
                        "severity": "actionable",
                        "agent": agent,
                        "detail": (
                            f"`{agent}` p95 ≈ {measured}m vs config {fallback}m "
                            f"(n={stats['count']})"
                        ),
                    }
                )

        for agent, block in sorted((usage.get("agents") or {}).items()):
            verify = block.get("verify") or {}
            ok = int(verify.get("ok") or 0)
            rework = int(verify.get("rework") or 0)
            noise = int(verify.get("noise") or 0)
            total = ok + rework + noise
            if total < min_verify:
                continue
            fail_rate = (rework + noise) / float(total)
            if fail_rate >= fail_rate_cap:
                drifts.append(
                    {
                        "kind": "verify",
                        "severity": "actionable",
                        "agent": agent,
                        "detail": (
                            f"`{agent}` verify fail-ish rate {fail_rate:.0%} "
                            f"(ok={ok} rework={rework} noise={noise})"
                        ),
                    }
                )
        return drifts

    def _write_runtime_page(self, cfg: dict[str, Any], *, sync: bool) -> None:
        fallbacks = dict(cfg.get("estimated_minutes") or {})
        lines = [
            f"# {RUNTIME_TITLE}",
            "",
            "Rolling execute duration for **ephemeral** specialists "
            "(persistent managers are not timed).",
            "",
            "| Agent | n | p50 min | p95 min | Config fallback min | Soft estimate min |",
            "|-------|---|---------|---------|---------------------|-------------------|",
        ]
        from company_brain.llm.duration import resolve_estimated_minutes

        agents = list_duration_agents(store=self._store)
        for agent in agents:
            stats = duration_stats(agent, store=self._store)
            fallback = int(fallbacks.get(agent) or 15)
            soft = resolve_estimated_minutes(agent, fallback, store=self._store)
            lines.append(
                f"| `{agent}` | {stats['count']} | "
                f"{stats['p50_ms'] / 60_000:.2f} | {stats['p95_ms'] / 60_000:.2f} | "
                f"{fallback} | {soft} |"
            )
        if not agents:
            lines.append("| — | 0 | — | — | — | — |")
        lines.append("")
        write_wiki_page(
            RUNTIME_PATH,
            RUNTIME_TITLE,
            "\n".join(lines),
            mode=UPDATE,
            section="admin",
            type_="page",
            sync=sync,
            sync_label="admin_only",
        )

    def _render_maintain(
        self,
        month: str,
        drifts: list[dict[str, Any]],
        status: dict[str, Any],
    ) -> str:
        lines = [
            f"# Maintain — {month}",
            "",
            f"**Period:** {month_title(month)} (`{month}`)",
            "",
            "Request an **admin coding session** to review drifts below. "
            "This agent does not edit yaml or open PRs.",
            "",
            "## Drift list",
            "",
        ]
        if not drifts:
            lines.append("- None — system looks within thresholds.")
        else:
            for d in drifts:
                lines.append(f"- **{d['kind']}:** {d['detail']}")
        lines.extend(
            [
                "",
                "## Coding session checklist",
                "",
                "- [ ] Review `admin/llm-expense/" + month + ".md`",
                "- [ ] Review [[admin/agent-runtime]] duration vs schedule buffers",
                "- [ ] Adjust `estimated_minutes` / work-ahead buffers where drift is real",
                "- [ ] Investigate verify rework/noise streaks",
                "",
                f"**Budget (current):** ${float(status.get('spent_usd') or 0):.2f} / "
                f"${float(status.get('limit_usd') or 0):.2f}",
                "",
            ]
        )
        return "\n".join(lines)

    def _notify(
        self,
        month: str,
        drifts: list[dict[str, Any]],
        status: dict[str, Any],
    ) -> bool:
        actionable = [d for d in drifts if d.get("severity") in {"actionable", "alert"}]
        if not actionable and not status.get("over_budget") and not status.get("near_limit"):
            wiki_admin_notifier().emit(
                Signal(
                    text=f"Admin maintain {month}: no actionable drift.",
                    severity=INFO,
                    silent=True,
                )
            )
            return False
        bullets = "\n".join(f"• {d['detail']}" for d in actionable[:8])
        text = (
            f"Admin coding session requested for {month}.\n"
            f"See wiki `admin/maintain/{month}.md`.\n"
            f"{bullets}"
        )
        return wiki_admin_notifier().emit(Signal(text=text, severity=ACTIONABLE))
