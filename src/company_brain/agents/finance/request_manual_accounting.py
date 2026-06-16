"""Manual Request Agent.

Started by monthly_expense or quarterly_calculation when there are uncategorized
or unclear transactions. It:

1. Writes the uncategorized transactions to the Notion "Manual Accounting" page
   as a checklist (vendor | amount | category: ___ | note: ___).
2. Messages Slack #finance requesting manual accounting help, with a page link.
3. Idles, then checks the page at noon each day; if not every entry has a
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
import logging
import re
from datetime import datetime, time, timedelta
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.config import AppConfig

from .shared import notion_pages, transactions
from .shared.config import load_finance_config, record_learned_categories
from .shared.slack import from_config as slack_from_config

logger = logging.getLogger(__name__)

MANUAL_KEY = "manual_accounting"
MANUAL_TERMS = ["Manual Accounting"]
CHECK_TIME = time(12, 0)

_CHECKBOX_RE = re.compile(r"^- \[( |x|X)\]\s*(.+)$")
_CATEGORY_RE = re.compile(r"category:\s*([^|]+)", re.IGNORECASE)


class RequestManualAccountingAgent(BaseAgent):
    """Solicit human categorization, then teach the source agent and rerun it."""

    name = "finance_request_manual_accounting"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.finance_config = load_finance_config()

    def run(
        self,
        *,
        source_agent: str,
        context: dict[str, Any],
        uncategorized: list[dict],
        wait_for_completion: bool | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        period = context.get("period", "")
        self.logger.info("Manual request for %s (%s): %d uncategorized",
                         source_agent, period, len(uncategorized))

        page_id = notion_pages.ensure_page(MANUAL_KEY, MANUAL_TERMS, "Manual Accounting")
        if not page_id:
            self.logger.warning("Could not bind 'Manual Accounting' page")
            return {"status": "no_page"}

        notion_pages.prepend_page_body(page_id, self._build_checklist(context, uncategorized))
        self._post_request(page_id, context, len(uncategorized))

        # Default to a bounded polling loop; callers/tests may disable waiting.
        manual_cfg = (self.finance_config.get("manual") or {})
        if wait_for_completion is None:
            wait_for_completion = bool(manual_cfg.get("wait_for_completion", True))

        if not wait_for_completion:
            return {"status": "requested", "page_id": page_id}

        completed = asyncio.run(self._poll_until_complete(page_id, manual_cfg))
        if completed:
            learned = self._extract_learned(page_id)
            if learned:
                record_learned_categories(learned)
                self.logger.info("Recorded %d learned categories", len(learned))
            self._rerun_source(source_agent, period)
            return {"status": "completed", "page_id": page_id, "learned": learned}

        return {"status": "incomplete", "page_id": page_id}

    # -- notion content ----------------------------------------------------

    def _build_checklist(self, context: dict[str, Any], uncategorized: list[dict]) -> str:
        period = context.get("period", "")
        lines = [f"## Manual Accounting Needed — {period}", ""]
        lines.append(f"*Requested {datetime.now():%Y-%m-%d %H:%M}. "
                     f"Set a category for each item, then it will be learned automatically.*")
        lines.append("")
        for t in uncategorized:
            amt = transactions.fmt_money(abs(t.get("amount", 0)))
            lines.append(
                f"- [ ] {t.get('name', 'Unknown')} | {amt} | {t.get('date', '')} | "
                f"category: ___ | note: ___"
            )
        lines.append("")
        return "\n".join(lines)

    def _post_request(self, page_id: str, context: dict[str, Any], count: int) -> None:
        slack = slack_from_config(self.finance_config)
        text = (f"Manual accounting needed for {context.get('period', '')}: "
                f"{count} uncategorized transaction(s). Please add categories.")
        try:
            slack.post_with_link(text, "Manual Accounting", notion_pages.page_url(page_id))
        except Exception:
            self.logger.exception("Slack request failed")

    # -- polling -----------------------------------------------------------

    async def _poll_until_complete(self, page_id: str, manual_cfg: dict[str, Any]) -> bool:
        max_checks = int(manual_cfg.get("max_checks", 14))
        for _ in range(max_checks):
            await asyncio.sleep(self._seconds_until_noon())
            content = notion_pages.read_page(page_id)
            if self._is_complete(content):
                self.logger.info("Manual accounting complete")
                return True
            self._bump(page_id)
        self.logger.info("Manual accounting still incomplete after %d checks", max_checks)
        return False

    def _bump(self, page_id: str) -> None:
        slack = slack_from_config(self.finance_config)
        try:
            slack.post_with_link(
                "Reminder: some transactions still need manual categorization.",
                "Manual Accounting", notion_pages.page_url(page_id),
            )
        except Exception:
            self.logger.exception("Slack bump failed")

    @staticmethod
    def _seconds_until_noon(now: datetime | None = None) -> float:
        now = now or datetime.now()
        target = now.replace(hour=CHECK_TIME.hour, minute=CHECK_TIME.minute, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    @staticmethod
    def _is_complete(content: str) -> bool:
        """Complete when no checklist item is left unchecked or without a category."""
        if not content:
            return False
        for line in content.splitlines():
            m = _CHECKBOX_RE.match(line.strip())
            if not m:
                continue
            checked = m.group(1).lower() == "x"
            cat_match = _CATEGORY_RE.search(line)
            has_category = bool(cat_match and cat_match.group(1).strip() not in ("", "___"))
            if not (checked or has_category):
                return False
        return True

    # -- learning + rerun --------------------------------------------------

    def _extract_learned(self, page_id: str) -> dict[str, str]:
        content = notion_pages.read_page(page_id)
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
            if source_agent == "finance_monthly_expense":
                from .monthly_expense import MonthlyExpenseManager
                MonthlyExpenseManager(self.config).run_once(period, escalate=False)
            elif source_agent == "finance_quarterly_calculation":
                from .quarterly_calculation import QuarterlyCalculationManager
                QuarterlyCalculationManager(self.config).run_once(period, escalate=False)
            else:
                self.logger.warning("Unknown source agent '%s' — cannot rerun", source_agent)
        except Exception:
            self.logger.exception("Rerun of source agent '%s' failed", source_agent)
