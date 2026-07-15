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
    receipt_router_day,
    receipt_router_time,
    sweep_time,
    workdays_only,
)
from company_brain.agents.operations.shared.profiles import (
    MANAGER_DISPATCH_ORDER,
    WEEKLY_DISPATCH,
    agent_enabled,
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
    track_duration = False

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
        from company_brain.agents.operations.shared.profiles import profile_spec
        from company_brain.runtime import get_runtime

        spec = profile_spec(self.mailbox)
        self.logger.info("Gmail manager dispatch pass (profile=%s)", spec.name)
        runtime = get_runtime()
        dispatch_map = _dispatch_agent_classes()

        for key in MANAGER_DISPATCH_ORDER:
            if key in WEEKLY_DISPATCH:
                continue
            if not agent_enabled(key, self.mailbox):
                continue
            cls = dispatch_map.get(key)
            if cls:
                self._run_agent(runtime, cls)

        now = at or datetime.now()
        if agent_enabled("ingest_queue_review", self.mailbox) and is_scheduled_moment(
            now,
            ingest_review_day(),
            ingest_review_time(),
        ):
            self._run_agent(runtime, dispatch_map["ingest_queue_review"], ping_slack=True)
        if agent_enabled("receipt_router", self.mailbox) and is_scheduled_moment(
            now,
            receipt_router_day(),
            receipt_router_time(),
        ):
            self._run_agent(runtime, dispatch_map["receipt_router"])

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
        if not agent_enabled("inbox_sweep", self.mailbox):
            self.logger.info("inbox_sweep disabled for profile — skipping sweep")
            return
        self.logger.info("Gmail manager dispatching inbox_sweep")
        from company_brain.agents.operations.gmail.inbox_sweep import InboxSweepAgent
        from company_brain.runtime import get_runtime

        try:
            get_runtime().run(InboxSweepAgent, self.config, mailbox=self.mailbox)
        except Exception:
            self.logger.exception("inbox_sweep failed")


def _dispatch_agent_classes() -> dict[str, type]:
    from company_brain.agents.operations.gmail.attachment_router import AttachmentRouterAgent
    from company_brain.agents.operations.gmail.connection import ConnectionAgent
    from company_brain.agents.operations.gmail.customer_crm import CustomerCRMAgent
    from company_brain.agents.operations.gmail.customer_mail_notify import (
        CustomerMailNotifyAgent,
    )
    from company_brain.agents.operations.gmail.draft_reply import DraftReplyAgent
    from company_brain.agents.operations.gmail.duplicate_across_mailboxes import (
        DuplicateAcrossMailboxesAgent,
    )
    from company_brain.agents.operations.gmail.ext_meeting_scheduler import (
        ExtMeetingSchedulerAgent,
    )
    from company_brain.agents.operations.gmail.inbound_crm import InboundCrmAgent
    from company_brain.agents.operations.gmail.inbox_task import InboxTaskAgent
    from company_brain.agents.operations.gmail.ingest import IngestAgent
    from company_brain.agents.operations.gmail.ingest_queue_review import IngestQueueReviewAgent
    from company_brain.agents.operations.gmail.investor_tracker import InvestorTrackerAgent
    from company_brain.agents.operations.gmail.receipt_router import ReceiptRouterAgent
    from company_brain.agents.operations.gmail.team_on_it import TeamOnItAgent
    from company_brain.agents.operations.gmail.vendor_tracker import VendorTrackerAgent

    return {
        "duplicate_across_mailboxes": DuplicateAcrossMailboxesAgent,
        "inbox_task": InboxTaskAgent,
        "team_on_it": TeamOnItAgent,
        "draft_reply": DraftReplyAgent,
        "ext_meeting_scheduler": ExtMeetingSchedulerAgent,
        "ingest": IngestAgent,
        "attachment_router": AttachmentRouterAgent,
        "investor_tracker": InvestorTrackerAgent,
        "customer_mail_notify": CustomerMailNotifyAgent,
        "customer_crm": CustomerCRMAgent,
        "inbound_crm": InboundCrmAgent,
        "vendor_tracker": VendorTrackerAgent,
        "connection": ConnectionAgent,
        "ingest_queue_review": IngestQueueReviewAgent,
        "receipt_router": ReceiptRouterAgent,
    }
