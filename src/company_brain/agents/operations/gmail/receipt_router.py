"""Receipt Router Agent — weekly Ramp vs Gmail receipt gap report.

Friday 8am (configurable): compares Receipt-tagged Gmail routing records against
expected subscription sender domains and writes a gap report to the wiki.
Ramp cross-check is best-effort when ``RAMP_TOKEN`` is set (logs a reminder to
run finance agents for full reconciliation). Does not auto-forward mail
(human-approved cross-account forward is a future Composio/REST opt-in).

SDK: Neither (deterministic wiki write; optional Ramp token check).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.shared.gmail_config import mailbox_id
from company_brain.agents.operations.shared.linear_config import (
    receipt_router_wiki_path,
    subscription_sender_domains,
)
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig
from company_brain.wiki.publish import APPEND, write_wiki_page

SPECIALIST_KEY = "receipt_router"


class ReceiptRouterAgent(BaseAgent):
    """Weekly receipt coverage report for finance review."""

    name = "gmail_receipt_router"
    WRITE_MODE = "append"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def run(self, **kwargs: Any) -> dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        receipts = [
            r for r in self._store.iter_mailbox(self.mailbox)
            if "Receipts" in r.domain_tags
            and _parse_triaged(r.triaged_at) >= since
        ]
        domains_seen = {_domain_from(r.extracted.get("from", "")) for r in receipts}
        domains_seen.discard("")

        expected = set(subscription_sender_domains())
        missing = sorted(expected - domains_seen) if expected else []
        ramp_note = _ramp_status_note()

        when = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = [
            f"## Receipt routing — {when}\n",
            f"- Gmail receipts (7d): **{len(receipts)}**",
            f"- Subscription senders configured: **{len(expected)}**",
        ]
        if missing:
            lines.append(f"- **Missing receipt domains:** {', '.join(missing)}")
        else:
            lines.append("- No configured subscription domains missing receipts this week.")
        if ramp_note:
            lines.append(f"\n{ramp_note}\n")
        if missing:
            lines.append(
                "\n_Action: request forward from other connected mailboxes for the "
                "domains above (human-approved; enable Composio/REST forward when ready)._\n"
            )

        rel_path = receipt_router_wiki_path()
        write_wiki_page(
            rel_path, "Receipt Routing", "\n".join(lines), mode=APPEND, section="operations/gmail",
        )

        for record in receipts:
            if SPECIALIST_KEY not in record.handled:
                self._store.mark_handled(record, SPECIALIST_KEY)

        return {
            "receipts_count": len(receipts),
            "missing_domains": missing,
            "path": rel_path,
        }


def _parse_triaged(raw: str) -> datetime:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _domain_from(from_hdr: str) -> str:
    if "@" not in from_hdr:
        return from_hdr.lower()
    return from_hdr.split("@")[-1].split(">")[0].strip().lower()


def _ramp_status_note() -> str:
    import os
    if not os.getenv("RAMP_TOKEN", "").strip():
        return "_Ramp token not set — full card-receipt reconciliation deferred to finance agents._"
    return "_Ramp connected — run `ramp_card_spend` / finance monthly reports for transaction-level receipt matching._"
