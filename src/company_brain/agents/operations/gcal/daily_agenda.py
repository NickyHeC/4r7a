"""Daily Agenda Agent — optional morning Slack DM with today's meetings.

Disabled by default (`gcal.daily_agenda.enabled: false`). When enabled, runs
persistently and DMs the user a concise rundown of the day's calendar events.

SDK: Neither (deterministic Calendar REST + optional wiki context).
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import is_handled, mark_handled
from company_brain.agents.operations.gcal import gcal_rest as rest
from company_brain.agents.operations.shared.gcal_config import (
    daily_agenda_enabled,
    daily_agenda_slack_user,
    daily_agenda_time,
    timezone_name,
)
from company_brain.agents.operations.shared.operations_slack import daily_agenda_notifier
from company_brain.agents.operations.shared.scheduling import (
    is_workday,
    next_daily_times,
)
from company_brain.notify import ACTIONABLE, Signal


class DailyAgendaAgent(BaseAgent):
    """Morning Slack DM with today's meeting rundown."""

    name = "daily_agenda"

    def run(self, *, once: bool = False, target_date: date | None = None, **kwargs: Any) -> Any:
        if not daily_agenda_enabled():
            self.logger.info("daily_agenda disabled — skipping")
            return {"status": "disabled"}
        if once or target_date is not None:
            return self.run_once(target_date=target_date)
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        scheduled = daily_agenda_time()
        self.logger.info(
            "Daily agenda starting persistent loop (daily at %02d:%02d)",
            scheduled.hour,
            scheduled.minute,
        )
        while True:
            now = datetime.now()
            if self._should_run_today(now):
                try:
                    self.run_once()
                except Exception:
                    self.logger.exception("Daily agenda run failed")
            nxt = next_daily_times(datetime.now(), [scheduled], workdays_only=True)
            wait = (nxt - datetime.now()).total_seconds()
            self.logger.info("Next daily agenda at %s (sleep %.0fs)", nxt.isoformat(), wait)
            await asyncio.sleep(max(wait, 1))

    def _should_run_today(self, now: datetime) -> bool:
        if not is_workday(now):
            return False
        scheduled = daily_agenda_time()
        today_at = now.replace(
            hour=scheduled.hour, minute=scheduled.minute, second=0, microsecond=0,
        )
        return now >= today_at and not is_handled("daily_agenda", now.date().isoformat())

    def run_once(self, *, target_date: date | None = None) -> dict[str, Any]:
        user = daily_agenda_slack_user()
        if not user:
            self.logger.warning("daily_agenda enabled but slack_user not set")
            return {"status": "not_configured"}

        day = target_date or date.today()
        events = rest.events_for_day(day)
        if not events:
            text = f"*Agenda for {day.isoformat()}* ({timezone_name()})\n\nNo meetings today."
        else:
            lines = [f"*Agenda for {day.isoformat()}* ({timezone_name()})", ""]
            for event in events:
                lines.append(_format_event_line(event))
            text = "\n".join(lines)

        daily_agenda_notifier(user).emit(Signal(text=text, severity=ACTIONABLE))
        mark_handled("daily_agenda", day.isoformat())
        return {"status": "ok", "date": day.isoformat(), "events": len(events)}


def _format_event_line(event: dict[str, Any]) -> str:
    title = event.get("summary") or "Untitled"
    bounds = rest.parse_event_bounds(event)
    when = ""
    if bounds:
        start, _end = bounds
        when = start.strftime("%I:%M %p").lstrip("0")
    desc = (event.get("description") or "").strip().splitlines()
    context = desc[0][:120] if desc else ""
    if context:
        return f"• *{when}* {title} — {context}"
    return f"• *{when}* {title}"
