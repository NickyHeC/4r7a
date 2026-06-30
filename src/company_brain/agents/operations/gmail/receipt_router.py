"""Receipt Router Agent — route receipts to the Ramp inbox.

Friday 8am (configurable): checks whether expected subscription receipt mail
arrived at the destination inbox (where Ramp auto-grabs). When a receipt landed
in another company-domain mailbox, copies it into the destination via Gmail
insert (no external send). Ramp owns transaction documentation — this agent does
not reconcile card spend.

SDK: Neither (deterministic wiki write + Gmail REST insert).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail.receipt_forward import forward_missing_receipts
from company_brain.agents.operations.shared.gmail_config import (
    receipt_destination_mailbox,
    receipt_router_wiki_path,
    subscription_sender_domains,
)
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig
from company_brain.wiki.publish import APPEND, write_wiki_page

SPECIALIST_KEY = "receipt_router"


class ReceiptRouterAgent(BaseAgent):
    """Weekly receipt inbox routing for Ramp auto-attach."""

    name = "receipt_router"
    WRITE_MODE = "append"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = receipt_destination_mailbox()
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

        forward_result = forward_missing_receipts(
            since=since,
            missing_domains=set(missing),
            store=self._store,
        )

        when = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = [
            f"## Receipt routing — {when}\n",
            f"- Destination inbox (Ramp): **{self.mailbox}**",
            f"- Gmail receipts at destination (7d): **{len(receipts)}**",
            f"- Subscription senders configured: **{len(expected)}**",
        ]
        if missing:
            lines.append(f"- **Still missing at destination:** {', '.join(missing)}")
        else:
            lines.append("- All configured subscription senders seen at destination this week.")
        forwarded = int(forward_result.get("forwarded") or 0)
        if forwarded:
            lines.append(f"- **Copied from sibling mailboxes:** {forwarded}")
        if forward_result.get("errors"):
            lines.append(f"- Copy errors: {len(forward_result['errors'])}")
        lines.append(
            "\n_Ramp auto-attaches receipts from the destination inbox — no transaction "
            "reconciliation here._\n"
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
            "forwarded": forwarded,
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
