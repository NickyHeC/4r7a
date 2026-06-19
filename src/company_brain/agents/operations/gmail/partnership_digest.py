"""Partnership Digest Agent — weekly ranked partnership Slack digest.

Rates ``Cold Inbound/Partnership`` and ``Cold Inbound/Founder Networking`` for
company relevance; posts a ranked digest to Slack; archives lower-scoring mail
still in the inbox.

SDK: Neither (heuristics + REST archive).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import mailbox_id
from company_brain.agents.operations.shared.labels import archive
from company_brain.agents.operations.shared.mail_body import plain_text
from company_brain.agents.operations.shared.operations_slack import partnership_digest_slack
from company_brain.agents.operations.shared.routing import RoutingRecord, RoutingStore
from company_brain.config import AppConfig
from company_brain.notify import ACTIONABLE, Notifier, Signal

logger = logging.getLogger(__name__)

SPECIALIST_KEY = "partnership_digest"
PARTNERSHIP_TAGS = {"Cold Inbound/Partnership", "Cold Inbound/Founder Networking"}
RELEVANCE_KEYWORDS = (
    "strategic", "integration", "api", "enterprise", "revenue", "distribution",
    "co-marketing", "platform", "ecosystem", "b2b", "saas",
)
KEEP_TOP = 3
ARCHIVE_BELOW_SCORE = 2


class PartnershipDigestAgent(BaseAgent):
    """Weekly ranked digest for partnership and founder networking inbound."""

    name = "gmail_partnership_digest"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return bool(self._pending())

    def run(self, **kwargs: Any) -> dict[str, Any]:
        pending = self._pending()
        if not pending:
            return {"ranked": 0, "archived": 0}

        scored: list[tuple[int, RoutingRecord]] = []
        for record in pending:
            try:
                message = rest.get_message(record.message_id, mailbox=self.mailbox)
                scored.append((_score(record, message), record))
            except Exception:
                self.logger.exception("Partnership scoring failed for %s", record.message_id)

        scored.sort(key=lambda x: x[0], reverse=True)
        lines = [f"*Partnership digest* ({self.mailbox}) — {datetime.now(timezone.utc).date()}\n"]
        for score, record in scored[:10]:
            subject = record.extracted.get("subject", record.message_id)
            tag = next((t for t in record.domain_tags if t in PARTNERSHIP_TAGS), "")
            lines.append(f"• [{score}] {subject} ({tag})")

        slack = partnership_digest_slack()
        Notifier(channel_post=slack.post).emit(Signal(
            text="\n".join(lines), severity=ACTIONABLE,
        ))

        archived = 0
        keep_ids = {r.message_id for _, r in scored[:KEEP_TOP]}
        for score, record in scored:
            self._store.mark_handled(record, SPECIALIST_KEY)
            if record.message_id in keep_ids:
                continue
            if score >= ARCHIVE_BELOW_SCORE:
                continue
            try:
                if rest.is_in_inbox(rest.get_message(record.message_id, mailbox=self.mailbox)):
                    archive(record.message_id, mailbox=self.mailbox)
                    archived += 1
            except Exception:
                self.logger.exception("Partnership archive failed for %s", record.message_id)

        return {"ranked": len(scored), "archived": archived}

    def _pending(self):
        return self._store.unhandled_with_any_tag(
            SPECIALIST_KEY, PARTNERSHIP_TAGS, mailbox=self.mailbox,
        )


def _score(record: RoutingRecord, message: dict[str, Any]) -> int:
    subject = (record.extracted.get("subject") or rest.message_subject_from(message)).lower()
    body = plain_text(message, max_chars=2000).lower()
    blob = f"{subject} {body}"
    score = 0
    for kw in RELEVANCE_KEYWORDS:
        if kw in blob:
            score += 2
    if "partnership" in blob:
        score += 1
    if "founder" in blob and "network" in blob:
        score += 1
    return score
