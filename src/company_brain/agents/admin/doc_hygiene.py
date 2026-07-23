"""Doc hygiene — quarterly drift report for steady-state docs (review only).

Surfaces stale plans, handbook drift cues, and migrate-names reminders.
Humans / coding agents apply edits — this agent never auto-edits docs.

SDK: Neither (deterministic scan + wiki review page).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.admin.llm_ops_config import load_operations_raw
from company_brain.agents.base import BaseAgent
from company_brain.config import PROJECT_ROOT
from company_brain.llm.admin_notify import wiki_admin_notifier
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import UPDATE, write_wiki_page

REVIEW_TMPL = "admin/doc-hygiene/{period}.md"
STATE_PREFIX = "admin_manager:doc_hygiene:"

_DOC_ROOTS = (
    "README.md",
    "memory.md",
    "project_install.md",
    "docs/agents",
    "docs/tabled.md",
    "docs/plans",
)


def doc_hygiene_config() -> dict[str, Any]:
    raw = (load_operations_raw().get("admin") or {}).get("doc_hygiene") or {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        # 1=Jan, 4=Apr, 7=Jul, 10=Oct
        "months": [int(m) for m in (raw.get("months") or [1, 4, 7, 10])],
        "day": int(raw.get("day") or 10),
        "time": str(raw.get("time") or "10:00"),
        "stale_days": int(raw.get("stale_days") or 90),
    }


def current_quarter_period(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    q = (now.month - 1) // 3 + 1
    return f"{now.year}-Q{q}"


class DocHygieneAgent(BaseAgent):
    """Write a quarterly documentation drift review page."""

    name = "doc_hygiene"
    WRITE_MODE = UPDATE

    def run(
        self,
        *,
        period: str | None = None,
        sync: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        period = period or current_quarter_period()
        cfg = doc_hygiene_config()
        findings = self._scan(stale_days=int(cfg["stale_days"]))
        path = REVIEW_TMPL.format(period=period)
        body = self._render(period, findings)
        write_wiki_page(
            path,
            f"Doc Hygiene — {period}",
            body,
            mode=UPDATE,
            section="admin",
            type_="review",
            sync=sync,
            sync_label="admin_only",
            extra_frontmatter={
                "period": period,
                "report": "doc_hygiene",
                "auto_merge": False,
            },
        )
        wiki_admin_notifier().emit(
            Signal(
                text=(
                    f"*Doc hygiene* — `{period}`\n"
                    f"Review `{path}`. Apply edits manually / via coding agent."
                ),
                severity=ACTIONABLE,
            )
        )
        return {
            "status": "ok",
            "period": period,
            "path": path,
            "stale_plans": len(findings.get("stale_plans") or []),
            "auto_edited": 0,
        }

    def _scan(self, *, stale_days: int) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        stale_plans: list[str] = []
        plans_dir = PROJECT_ROOT / "docs" / "plans"
        if plans_dir.is_dir():
            for path in sorted(plans_dir.glob("*.md")):
                try:
                    age = (now - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)).days
                except OSError:
                    continue
                if age >= stale_days:
                    stale_plans.append(f"`docs/plans/{path.name}` ({age}d)")

        missing: list[str] = []
        for rel in _DOC_ROOTS:
            p = PROJECT_ROOT / rel
            if not p.exists():
                missing.append(rel)

        handbook = PROJECT_ROOT / "docs" / "agents"
        handbooks = sorted(p.name for p in handbook.glob("*.md")) if handbook.is_dir() else []

        return {
            "stale_plans": stale_plans,
            "missing_roots": missing,
            "handbooks": handbooks,
            "reminders": [
                "Run `company-brain migrate-names` (dry-run) after large wiki imports",
                "Fold shipped `docs/plans/*` into handbooks + `memory.md`, then delete the plan",
                "Keep `docs/tabled.md` as the only deferred registry",
            ],
        }

    def _render(self, period: str, findings: dict[str, Any]) -> str:
        now = datetime.now(timezone.utc).isoformat()
        lines = [
            f"# Doc Hygiene — {period}",
            "",
            f"_Generated {now}_",
            "",
            "Review only. **Never auto-edit** README / handbooks / plans.",
            "",
            "## Stale plans",
            "",
        ]
        stale = findings.get("stale_plans") or []
        if not stale:
            lines.append("_No plans older than threshold._")
        else:
            for item in stale:
                lines.append(f"- {item}")
        lines.extend(["", "## Missing expected roots", ""])
        missing = findings.get("missing_roots") or []
        if not missing:
            lines.append("_All expected roots present._")
        else:
            for item in missing:
                lines.append(f"- `{item}`")
        lines.extend(["", "## Handbooks present", ""])
        for name in findings.get("handbooks") or []:
            lines.append(f"- `{name}`")
        lines.extend(["", "## Reminders", ""])
        for r in findings.get("reminders") or []:
            lines.append(f"- {r}")
        lines.append("")
        return "\n".join(lines)
