"""Request Manual Management Agent — human review loop for stale Linear tasks.

Mirrors ``request_manual_accounting``: writes a wiki checklist (MD first, Notion
mirror), pings Slack, polls until entries are complete, then applies approved
status changes via ``task_propagate`` and ``linear_client.update_issue``.

SDK: Neither (deterministic parse + Linear GraphQL).
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, time, timedelta
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.linear import linear_client
from company_brain.agents.engineering.linear.task_bindings import TaskBindingStore
from company_brain.agents.engineering.linear.task_propagate import record_status_change
from company_brain.agents.engineering.shared.linear_config import manual_cfg, team_id, team_key
from company_brain.agents.engineering.shared.linear_slack import linear_notifier
from company_brain.config import AppConfig
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import read_wiki_page, write_wiki_page

MANUAL_PATH = "engineering/linear/manual-management.md"
MANUAL_TITLE = "Linear Manual Management"

_CHECKBOX_RE = re.compile(r"^- \[( |x|X)\]\s*(.+)$")
_PROPOSED_RE = re.compile(r"proposed:\s*([^|]+)", re.IGNORECASE)
_IDENTIFIER_RE = re.compile(r"\b([A-Z]{2,10}-\d+)\b")


class RequestManualManagementAgent(BaseAgent):
    """Solicit human status decisions, then apply approved Linear updates."""

    name = "linear_request_manual_management"
    WRITE_MODE = "update"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._bindings = TaskBindingStore()
        self._manual = manual_cfg()

    def run(
        self,
        *,
        source_agent: str,
        proposals: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
        wait_for_completion: bool | None = None,
        sync: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not proposals:
            return {"status": "empty"}

        ctx = context or {}
        self.logger.info(
            "Manual management for %s: %d proposal(s)",
            source_agent,
            len(proposals),
        )

        write_wiki_page(
            MANUAL_PATH,
            MANUAL_TITLE,
            self._build_checklist(source_agent, ctx, proposals),
            mode="update",
            section="engineering/linear",
            sync=sync,
        )
        self._post_request(len(proposals))

        if wait_for_completion is None:
            wait_for_completion = bool(self._manual.get("wait_for_completion", True))

        if not wait_for_completion:
            return {"status": "requested"}

        completed = asyncio.run(self._poll_until_complete())
        if completed:
            applied = self._apply_approved()
            return {"status": "completed", "applied": applied}

        return {"status": "incomplete"}

    def _build_checklist(
        self,
        source_agent: str,
        context: dict[str, Any],
        proposals: list[dict[str, Any]],
    ) -> str:
        period = context.get("period", datetime.now().strftime("%Y-%m-%d"))
        lines = [
            f"## Manual Management — {period}",
            "",
            f"*From `{source_agent}`. Set **proposed** status and check each row.*",
            "",
        ]
        for p in proposals:
            ident = p.get("identifier") or "?"
            title = p.get("title") or ""
            current = p.get("current_status") or "?"
            suggested = p.get("suggested_status") or "___"
            reason = p.get("reason") or ""
            suffix = f" | note: {reason}" if reason else " | note: ___"
            lines.append(
                f"- [ ] {ident} | {title} | current: {current} | "
                f"proposed: {suggested}{suffix}"
            )
        lines.append("")
        return "\n".join(lines)

    def _post_request(self, count: int) -> None:
        try:
            linear_notifier().emit(Signal(
                text=f"Linear manual management: {count} issue(s) need review.",
                severity=ACTIONABLE,
            ))
        except Exception:
            self.logger.exception("Slack request failed")

    async def _poll_until_complete(self) -> bool:
        max_checks = int(self._manual.get("max_checks", 14))
        check_time = self._check_time()
        for _ in range(max_checks):
            await asyncio.sleep(self._seconds_until(check_time))
            content = read_wiki_page(MANUAL_PATH)
            if self._is_complete(content):
                return True
            self._bump()
        return False

    def _check_time(self) -> time:
        raw = str(self._manual.get("check_time") or "12:00")
        hour, minute = raw.split(":")
        return time(int(hour), int(minute))

    @staticmethod
    def _seconds_until(target: time, now: datetime | None = None) -> float:
        now = now or datetime.now()
        candidate = now.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
        if now >= candidate:
            candidate += timedelta(days=1)
        return (candidate - now).total_seconds()

    def _bump(self) -> None:
        try:
            linear_notifier().emit(Signal(
                text="Reminder: Linear manual management items still need review.",
                severity=ACTIONABLE,
            ))
        except Exception:
            self.logger.exception("Slack bump failed")

    @staticmethod
    def _is_complete(content: str) -> bool:
        found = False
        for line in content.splitlines():
            m = _CHECKBOX_RE.match(line.strip())
            if not m:
                continue
            found = True
            checked = m.group(1).lower() == "x"
            body = m.group(2)
            proposed = _PROPOSED_RE.search(body)
            has_proposed = bool(
                proposed and proposed.group(1).strip() not in ("", "___", "Review")
            )
            if not (checked or has_proposed):
                return False
        return found

    def _apply_approved(self) -> list[dict[str, Any]]:
        content = read_wiki_page(MANUAL_PATH)
        applied: list[dict[str, Any]] = []
        for line in content.splitlines():
            m = _CHECKBOX_RE.match(line.strip())
            if not m or m.group(1).lower() != "x":
                continue
            body = m.group(2)
            ident_match = _IDENTIFIER_RE.search(body)
            proposed_match = _PROPOSED_RE.search(body)
            if not ident_match or not proposed_match:
                continue
            ident = ident_match.group(1)
            new_status = proposed_match.group(1).strip()
            if not new_status or new_status in ("___", "Review"):
                continue
            result = self._apply_status(ident, new_status)
            if result:
                applied.append(result)
        return applied

    def _apply_status(self, identifier: str, new_status: str) -> dict[str, Any] | None:
        binding = self._bindings.find_by_linear(identifier)
        state_id = linear_client.resolve_state_id(
            new_status,
            team_id=team_id() or None,
            team_key=team_key() or None,
        )
        if not state_id:
            self.logger.warning("Could not resolve state '%s' for %s", new_status, identifier)
            return None
        try:
            issue = linear_client.update_issue(identifier, state_id=state_id)
        except Exception:
            self.logger.exception("Linear update failed for %s", identifier)
            return None

        if binding:
            record_status_change(
                binding,
                platform="linear",
                field="status",
                value=new_status,
                source="system:request_manual_management",
                store=self._bindings,
                sync_notion=False,
            )
        return {
            "identifier": identifier,
            "status": new_status,
            "issue_id": issue.get("id"),
        }
