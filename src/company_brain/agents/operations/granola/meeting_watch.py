"""Granola Meeting Watch — ingest notes after calendar meetings end.

Persistent agent: polls Google Calendar for recently ended meetings, dispatches
``granola_ingest`` per meeting (no LLM until the meeting ends), then
``granola_task``. A weekly ``granola_miss_check`` is the safety net for any
meetings the calendar-driven ingest missed.

SDK: Neither (calendar poll + orchestration).
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import is_handled, mark_handled
from company_brain.agents.operations.shared import granola_config as cfg
from company_brain.config import AppConfig

MEETING_HANDLED_PREFIX = "granola_meeting:"


class GranolaMeetingWatchAgent(BaseAgent):
    """Wake after meetings end; dispatch ingest + task extraction."""

    name = "granola_meeting_watch"

    def run(self, *, once: bool = False, **kwargs: Any) -> Any:
        if once:
            return self.run_once()
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        interval = cfg.watch_interval_minutes()
        self.logger.info("Granola meeting watch starting (poll every %d min)", interval)
        while True:
            try:
                self.run_once()
            except Exception:
                self.logger.exception("Granola meeting watch failed")
            await asyncio.sleep(max(interval * 60, 60))

    def run_once(self) -> dict[str, Any]:
        if not cfg.granola_is_configured():
            return {"status": "not_configured"}

        ended = self._ended_meetings()
        dispatched = 0
        for event in ended:
            event_id = event.get("id") or ""
            if not event_id or is_handled("granola_meeting", event_id):
                continue
            title = event.get("summary") or ""
            day = self._event_day(event)
            result = self._dispatch_ingest(day, event_title=title)
            mark_handled("granola_meeting", event_id)
            dispatched += 1
            self.logger.info("Post-meeting ingest for %s: %s", title, result.get("status"))

        miss = self._maybe_miss_check(datetime.now())
        return {
            "ended_meetings": len(ended),
            "dispatched": dispatched,
            "miss_check": miss,
        }

    def _ended_meetings(self) -> list[dict[str, Any]]:
        try:
            from company_brain.agents.operations.gcal import gcal_rest as gcal
        except Exception:
            return []

        now = datetime.now(timezone.utc)
        buffer = timedelta(minutes=cfg.post_meeting_buffer_minutes())
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=12)
        try:
            events = gcal.list_events(start, now)
        except Exception:
            self.logger.exception("Calendar list failed")
            return []

        ended: list[dict[str, Any]] = []
        for event in events:
            end = _event_end(event)
            if end is None:
                continue
            if end + buffer <= now.astimezone(end.tzinfo or timezone.utc):
                ended.append(event)
        return ended

    def _dispatch_ingest(self, day: date, *, event_title: str) -> dict[str, Any]:
        from company_brain.agents.operations.granola.granola_ingest import GranolaIngestAgent
        from company_brain.runtime import get_runtime

        return get_runtime().run(
            GranolaIngestAgent,
            self.config,
            target_date=day,
            event_title=event_title,
            dispatch_task=True,
        )

    def _maybe_miss_check(self, now: datetime) -> dict[str, Any] | None:
        if now.strftime("%A").lower() != cfg.miss_check_day():
            return None
        check = cfg.miss_check_time()
        scheduled = now.replace(hour=check.hour, minute=check.minute, second=0, microsecond=0)
        if now < scheduled:
            return None
        week_key = now.strftime("%G-W%V")
        if is_handled("granola_miss_check", week_key):
            return None
        from company_brain.agents.operations.granola.granola_miss_check import GranolaMissCheckAgent
        from company_brain.runtime import get_runtime

        mark_handled("granola_miss_check", week_key)
        return get_runtime().run(GranolaMissCheckAgent, self.config)

    @staticmethod
    def _event_day(event: dict[str, Any]) -> date:
        end = _event_end(event)
        if end:
            return end.date()
        start = _event_start(event)
        if start:
            return start.date()
        return date.today()


def _event_end(event: dict[str, Any]) -> datetime | None:
    return _parse_event_time(event.get("end"))


def _event_start(event: dict[str, Any]) -> datetime | None:
    return _parse_event_time(event.get("start"))


def _parse_event_time(block: dict[str, Any] | None) -> datetime | None:
    if not block:
        return None
    raw = block.get("dateTime") or block.get("date")
    if not raw:
        return None
    try:
        if "T" in raw:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return datetime.fromisoformat(raw + "T00:00:00+00:00")
    except ValueError:
        return None
