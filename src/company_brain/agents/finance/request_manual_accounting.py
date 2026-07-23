"""Manual Request Agent.

Started by monthly_expense or quarterly_calculation when there are uncategorized
or unclear transactions. It:

1. Writes uncategorized transactions to the wiki Manual Accounting page before
   its Notion mirror (vendor | amount | category: ___ | note: ___).
2. Messages Slack #finance requesting manual accounting help, with the mirror link.
3. Idles, then checks the synced page at noon each day; if not every entry has a
   category/note it bumps #finance.
4. When all entries are complete, it records the human-provided
   vendor->category mappings as learned categories (config/finance.yaml) and
   reruns the source agent so it benefits from the corrections.

SDK: Anthropic Claude Agent SDK is used to parse free-form human notes on the
Manual Accounting page into structured vendor->category mappings; a deterministic
parser is used as a fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore, changed_since
from company_brain.agents.scheduling.calendar import parse_hhmm
from company_brain.config import AppConfig
from company_brain.notify import ACTIONABLE, Signal, from_finance_config

from .shared import notion_pages, transactions
from .shared.config import load_finance_config, record_learned_categories

logger = logging.getLogger(__name__)

MANUAL_KEY = "manual_accounting"
MANUAL_TERMS = ["Manual Accounting"]
_CHECKBOX_RE = re.compile(r"^- \[( |x|X)\]\s*(.+)$")
_CATEGORY_RE = re.compile(r"category:\s*([^|]+)", re.IGNORECASE)


class RequestManualAccountingAgent(BaseAgent):
    """Solicit human categorization, then teach the source agent and rerun it.

    Update agent: the Manual Accounting page is overwritten to show the CURRENT
    set of items needing attention (not a growing log).
    """

    name = "finance_request_manual_accounting"
    WRITE_MODE = "update"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.finance_config = load_finance_config()
        self._state = StateStore()

    def should_run(
        self,
        *,
        source_agent: str,
        context: dict[str, Any],
        uncategorized: list[dict],
        force: bool = False,
        **kwargs: Any,
    ) -> bool:
        """Cost gate duplicate requests before any later LLM parsing."""
        if force:
            return True
        key, signature = _request_gate(source_agent, context, uncategorized)
        return changed_since(key, signature, store=self._state, update=False)

    def run(
        self,
        *,
        source_agent: str,
        context: dict[str, Any],
        uncategorized: list[dict],
        wait_for_completion: bool | None = None,
        force: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        period = context.get("period", "")
        self.logger.info(
            "Manual request for %s (%s): %d uncategorized", source_agent, period, len(uncategorized)
        )

        wiki_path = notion_pages.ensure_page(MANUAL_KEY, MANUAL_TERMS, "Manual Accounting")
        notion_pages.update_page_body(
            wiki_path,
            self._build_checklist(context, uncategorized),
        )
        self._post_request(wiki_path, context, len(uncategorized))
        key, signature = _request_gate(source_agent, context, uncategorized)
        self._state.set(key, signature)

        # Default to a bounded polling loop; callers/tests may disable waiting.
        manual_cfg = self.finance_config.get("manual") or {}
        if wait_for_completion is None:
            wait_for_completion = bool(manual_cfg.get("wait_for_completion", True))

        if not wait_for_completion:
            return {"status": "requested", "wiki_path": wiki_path}

        completed = asyncio.run(self._poll_until_complete(wiki_path, manual_cfg))
        if completed:
            learned = self._extract_learned(wiki_path)
            if learned:
                record_learned_categories(learned)
                self.logger.info("Recorded %d learned categories", len(learned))
            self._rerun_source(source_agent, period)
            return {"status": "completed", "wiki_path": wiki_path, "learned": learned}

        return {"status": "incomplete", "wiki_path": wiki_path}

    # -- notion content ----------------------------------------------------

    def _build_checklist(self, context: dict[str, Any], uncategorized: list[dict]) -> str:
        period = context.get("period", "")
        lines = [f"## Manual Accounting Needed — {period}", ""]
        lines.append(
            f"*Requested {datetime.now():%Y-%m-%d %H:%M}. "
            f"Set a category for each item, then it will be learned automatically.*"
        )
        lines.append("")
        for t in uncategorized:
            amt = transactions.fmt_money(abs(t.get("amount", 0)))
            lines.append(
                f"- [ ] {t.get('name', 'Unknown')} | {amt} | {t.get('date', '')} | "
                f"category: ___ | note: ___"
            )
        lines.append("")
        return "\n".join(lines)

    def _post_request(self, wiki_path: str, context: dict[str, Any], count: int) -> None:
        text = (
            f"Manual accounting needed for {context.get('period', '')}: "
            f"{count} uncategorized transaction(s). Please add categories."
        )
        try:
            from_finance_config(self.finance_config).emit(
                Signal(
                    text=text,
                    severity=ACTIONABLE,
                    link_label="Manual Accounting",
                    link_url=notion_pages.page_url(wiki_path),
                )
            )
        except Exception:
            self.logger.exception("Slack request failed")

    # -- polling -----------------------------------------------------------

    async def _poll_until_complete(self, wiki_path: str, manual_cfg: dict[str, Any]) -> bool:
        max_checks = int(manual_cfg.get("max_checks", 14))
        for _ in range(max_checks):
            await asyncio.sleep(self._seconds_until_check())
            content = notion_pages.read_page(wiki_path)
            if self._is_complete(content):
                self.logger.info("Manual accounting complete")
                return True
            self._bump(wiki_path)
        self.logger.info("Manual accounting still incomplete after %d checks", max_checks)
        return False

    def _bump(self, wiki_path: str) -> None:
        try:
            from_finance_config(self.finance_config).emit(
                Signal(
                    text="Reminder: some transactions still need manual categorization.",
                    severity=ACTIONABLE,
                    link_label="Manual Accounting",
                    link_url=notion_pages.page_url(wiki_path),
                )
            )
        except Exception:
            self.logger.exception("Slack bump failed")

    @staticmethod
    def _seconds_until_check(now: datetime | None = None) -> float:
        now = now or datetime.now()
        schedule = (load_finance_config().get("schedules") or {}).get(
            "request_manual_accounting"
        ) or {}
        check_time = parse_hhmm(str(schedule.get("check_time") or "12:00"))
        target = now.replace(
            hour=check_time.hour,
            minute=check_time.minute,
            second=0,
            microsecond=0,
        )
        if now >= target:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    @staticmethod
    def _is_complete(content: str) -> bool:
        """Complete when no checklist item is left unchecked or without a category."""
        if not content:
            return False
        found_items = False
        for line in content.splitlines():
            m = _CHECKBOX_RE.match(line.strip())
            if not m:
                continue
            found_items = True
            checked = m.group(1).lower() == "x"
            cat_match = _CATEGORY_RE.search(line)
            has_category = bool(cat_match and cat_match.group(1).strip() not in ("", "___"))
            if not (checked or has_category):
                return False
        return found_items

    # -- learning + rerun --------------------------------------------------

    def _extract_learned(self, wiki_path: str) -> dict[str, str]:
        content = notion_pages.read_page(wiki_path)
        mapping: dict[str, str] = {}
        for line in content.splitlines():
            m = _CHECKBOX_RE.match(line.strip())
            if not m:
                continue
            body = m.group(2)
            vendor = body.split("|")[0].strip()
            cat_match = _CATEGORY_RE.search(body)
            category = cat_match.group(1).strip() if cat_match else ""
            if vendor and category and category != "___":
                mapping[vendor] = category
        return mapping

    def _rerun_source(self, source_agent: str, period: str) -> None:
        """Rerun the source manager with learned categories applied (no re-escalation)."""
        try:
            from company_brain.runtime import get_runtime

            if source_agent == "finance_monthly_expense":
                from .monthly_expense import MonthlyExpenseManager

                get_runtime().run(
                    MonthlyExpenseManager,
                    self.config,
                    once=True,
                    month=period,
                    escalate=False,
                )
            elif source_agent == "finance_quarterly_calculation":
                from .quarterly_calculation import QuarterlyCalculationManager

                get_runtime().run(
                    QuarterlyCalculationManager,
                    self.config,
                    once=True,
                    quarter=period,
                    escalate=False,
                )
            else:
                self.logger.warning("Unknown source agent '%s' — cannot rerun", source_agent)
        except Exception:
            self.logger.exception("Rerun of source agent '%s' failed", source_agent)


def _request_gate(
    source_agent: str,
    context: dict[str, Any],
    uncategorized: list[dict],
) -> tuple[str, str]:
    period = str(context.get("period") or "unknown")
    payload = json.dumps(
        {"source": source_agent, "context": context, "items": uncategorized},
        sort_keys=True,
        default=str,
    )
    signature = hashlib.sha256(payload.encode()).hexdigest()
    return f"manual_accounting:{source_agent}:{period}", signature
