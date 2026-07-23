"""Security Triage — heuristic security mail; never archive; alert + wiki log.

LLM only for borderline confidence. Humans decide.

SDK: Neither (heuristics + optional Claude confirm for borderline).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.shared.gmail_config import mailbox_id
from company_brain.agents.operations.shared.operations_slack import channel_notifier
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig
from company_brain.notify import ALERT, Signal
from company_brain.wiki.publish import APPEND, format_append_section, write_wiki_page

SPECIALIST_KEY = "security_triage"
WIKI_PATH = "operations/gmail/security-log.md"
TITLE = "Security Triage Log"


class SecurityTriageAgent(BaseAgent):
    """Alert + append wiki log for Security-tagged routing records. Never archives."""

    name = "security_triage"
    WRITE_MODE = APPEND

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return bool(self._pending())

    def run(self, **kwargs: Any) -> dict[str, Any]:
        logged = 0
        alerted = 0
        for record in self._pending():
            try:
                confidence = str((record.extracted or {}).get("security_confidence") or "high")
                if confidence == "borderline" and not self._confirm_borderline(record):
                    self._store.mark_handled(record, SPECIALIST_KEY)
                    continue
                self._append_log(record)
                if self._alert(record):
                    alerted += 1
                logged += 1
                # Explicit: never archive security mail
                self._store.mark_handled(record, SPECIALIST_KEY)
            except Exception:
                self.logger.exception("security_triage failed for %s", record.message_id)
        return {
            "status": "ok",
            "logged": logged,
            "alerted": alerted,
            "archived": 0,
        }

    def _pending(self):
        return self._store.unhandled_for(
            SPECIALIST_KEY,
            mailbox=self.mailbox,
            domain_tag="Security",
        )

    def _append_log(self, record) -> None:
        subject = (record.extracted or {}).get("subject") or "(no subject)"
        from_ = (record.extracted or {}).get("from") or ""
        reasons = (record.extracted or {}).get("security_reasons") or []
        conf = (record.extracted or {}).get("security_confidence") or ""
        section = format_append_section(
            f"Security — {subject[:80]}",
            (
                f"**From:** {from_}\n"
                f"**Mailbox:** `{self.mailbox}`\n"
                f"**Message id:** `{record.message_id}`\n"
                f"**Confidence:** {conf}\n"
                f"**Signals:** {', '.join(str(r) for r in reasons) or '—'}\n"
                f"**Action:** human review — do not archive automatically\n"
            ),
            trigger="security_triage",
        )
        write_wiki_page(
            WIKI_PATH,
            TITLE,
            section,
            mode=APPEND,
            section="operations/gmail",
            sync_label="admin_only",
        )

    def _alert(self, record) -> bool:
        subject = (record.extracted or {}).get("subject") or "(no subject)"
        from_ = (record.extracted or {}).get("from") or ""
        text = (
            f"Security mail flagged — `{subject[:120]}` from {from_}. "
            f"See wiki `{WIKI_PATH}` (never auto-archived)."
        )
        try:
            from company_brain.agents.operations.shared.gmail_config import slack_cfg

            channel = str(slack_cfg().get("ingest_channel") or "#ingest")
            return channel_notifier(channel).emit(Signal(text=text, severity=ALERT))
        except Exception:
            self.logger.exception("security_triage Slack alert failed")
            return False

    def _confirm_borderline(self, record) -> bool:
        """Optional LLM confirm for borderline — default keep (fail closed to alert)."""
        # v1: treat borderline as real enough to log; skip expensive LLM unless configured
        return True


__all__ = ["SecurityTriageAgent", "WIKI_PATH", "SPECIALIST_KEY"]
