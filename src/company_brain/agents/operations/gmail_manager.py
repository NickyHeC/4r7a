"""Gmail Manager — dispatch specialists on workday schedule.

Persistent agent: 8am, 12pm, 4pm workdays dispatches Phase 2–4 specialists;
10pm workdays runs inbox_sweep.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.shared.gmail_config import (
    ingest_review_day,
    ingest_review_time,
    mailbox_id,
    manager_times,
    partnership_digest_day,
    partnership_digest_time,
    sweep_time,
    workdays_only,
)
from company_brain.agents.operations.shared.linear_config import (
    receipt_router_day,
    receipt_router_time,
)
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.agents.operations.shared.scheduling import (
    is_scheduled_moment,
    is_workday,
    next_daily_times,
)
from company_brain.config import AppConfig


class GmailManager(BaseAgent):
    """Persistent manager for the Gmail platform within operations."""

    name = "gmail_manager"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def run(self, **kwargs: Any) -> Any:
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        self.logger.info("Gmail manager starting persistent loop")
        dispatch_times = manager_times()
        sweep = sweep_time()
        all_times = sorted(set(dispatch_times + [sweep]))

        while True:
            now = datetime.now()
            nxt = next_daily_times(now, all_times, workdays_only=workdays_only())
            wait = (nxt - now).total_seconds()
            self.logger.info("Next manager run at %s (sleep %.0fs)", nxt.isoformat(), wait)
            await asyncio.sleep(max(wait, 1))

            if workdays_only() and not is_workday():
                continue

            sweep_at = sweep.replace(second=0, microsecond=0)
            if nxt.time().replace(second=0, microsecond=0) == sweep_at:
                await self._run_sweep()
            else:
                await self._dispatch_pass(at=nxt)

    async def _dispatch_pass(self, *, at: datetime | None = None) -> None:
        self.logger.info("Gmail manager dispatch pass")
        from company_brain.agents.operations.gmail.attachment_router import AttachmentRouterAgent
        from company_brain.agents.operations.gmail.customer_crm import CustomerCRMAgent
        from company_brain.agents.operations.gmail.draft_reply import DraftReplyAgent
        from company_brain.agents.operations.gmail.duplicate_across_mailboxes import (
            DuplicateAcrossMailboxesAgent,
        )
        from company_brain.agents.operations.gmail.gmail_crm import GmailCRMAgent
        from company_brain.agents.operations.gmail.gmail_customer_support import (
            GmailCustomerSupportAgent,
        )
        from company_brain.agents.operations.gmail.gmail_ingest import GmailIngestAgent
        from company_brain.agents.operations.gmail.growth_inbound import GrowthInboundAgent
        from company_brain.agents.operations.gmail.inbox_task import InboxTaskAgent
        from company_brain.agents.operations.gmail.ingest_queue_review import (
            IngestQueueReviewAgent,
        )
        from company_brain.agents.operations.gmail.investor_tracker import InvestorTrackerAgent
        from company_brain.agents.operations.gmail.partnership_digest import (
            PartnershipDigestAgent,
        )
        from company_brain.agents.operations.gmail.receipt_router import ReceiptRouterAgent
        from company_brain.agents.operations.gmail.recruiting_inbound import (
            RecruitingInboundAgent,
        )
        from company_brain.agents.operations.gmail.team_on_it import TeamOnItAgent
        from company_brain.agents.operations.gmail.vendor_tracker import VendorTrackerAgent
        from company_brain.runtime import get_runtime

        runtime = get_runtime()
        self._run_agent(runtime, DuplicateAcrossMailboxesAgent)

        for agent_cls in (
            InboxTaskAgent,
            TeamOnItAgent,
            DraftReplyAgent,
            GmailIngestAgent,
            AttachmentRouterAgent,
            InvestorTrackerAgent,
            GmailCustomerSupportAgent,
            CustomerCRMAgent,
            GrowthInboundAgent,
            VendorTrackerAgent,
            GmailCRMAgent,
            RecruitingInboundAgent,
        ):
            self._run_agent(runtime, agent_cls)

        now = at or datetime.now()
        if is_scheduled_moment(now, ingest_review_day(), ingest_review_time()):
            self._run_agent(runtime, IngestQueueReviewAgent, ping_slack=True)
        if is_scheduled_moment(now, partnership_digest_day(), partnership_digest_time()):
            self._run_agent(runtime, PartnershipDigestAgent)
        if is_scheduled_moment(now, receipt_router_day(), receipt_router_time()):
            self._run_agent(runtime, ReceiptRouterAgent)

        records = list(self._store.iter_mailbox(self.mailbox))
        with_attention = sum(1 for r in records if r.attention)
        unhandled = sum(1 for r in records if not r.handled)
        self.logger.info(
            "Routing snapshot: %d records, %d with attention, %d with any unhandled specialist",
            len(records),
            with_attention,
            unhandled,
        )

    def _run_agent(self, runtime, agent_cls: type, **kwargs: Any) -> None:
        try:
            runtime.run(agent_cls, self.config, mailbox=self.mailbox, **kwargs)
        except Exception:
            self.logger.exception("%s dispatch failed", agent_cls.__name__)

    async def _run_sweep(self) -> None:
        self.logger.info("Gmail manager dispatching inbox_sweep")
        from company_brain.agents.operations.gmail.inbox_sweep import InboxSweepAgent
        from company_brain.runtime import get_runtime

        try:
            get_runtime().run(InboxSweepAgent, self.config, mailbox=self.mailbox)
        except Exception:
            self.logger.exception("inbox_sweep failed")
