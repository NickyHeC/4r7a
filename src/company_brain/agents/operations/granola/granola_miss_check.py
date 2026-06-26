"""Granola miss check — use meeting-watch handled markers."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import is_handled
from company_brain.agents.operations.shared import granola_config as cfg
from company_brain.config import AppConfig
from company_brain.wiki.publish import write_wiki_page

REPORT_PATH = "operations/granola/missed-notes.md"
REPORT_TITLE = "Granola Missed Notes"


class GranolaMissCheckAgent(BaseAgent):
    """Report calendar meetings without a post-meeting Granola ingest."""

    name = "granola_miss_check"
    WRITE_MODE = "update"

    def run(self, *, sync: bool = True, **kwargs: Any) -> dict[str, Any]:
        if not cfg.granola_is_configured():
            return {"status": "not_configured"}

        now = datetime.now(timezone.utc)
        week_start = now - timedelta(days=7)
        events = self._calendar_events(week_start, now)

        missing: list[str] = []
        for event in events:
            if not _looks_like_meeting(event):
                continue
            event_id = event.get("id") or ""
            if not event_id or is_handled("granola_meeting", event_id):
                continue
            title = event.get("summary") or "Untitled"
            day = _event_day(event)
            missing.append(f"- **{day.isoformat()}** — {title}")

        body = self._render_body(missing, week_start=week_start, now=now)
        write_wiki_page(
            REPORT_PATH,
            REPORT_TITLE,
            body,
            mode="update",
            section="operations/granola",
            sync=sync,
        )
        return {"events": len(events), "missing": len(missing)}

    @staticmethod
    def _calendar_events(start: datetime, end: datetime) -> list[dict[str, Any]]:
        try:
            from company_brain.agents.operations.gcal import gcal_rest as gcal
            return gcal.list_events(start, end)
        except Exception:
            return []

    @staticmethod
    def _render_body(missing: list[str], *, week_start: datetime, now: datetime) -> str:
        lines = [
            "# Granola Missed Notes",
            "",
            f"_Week {week_start.date().isoformat()} → {now.date().isoformat()}_",
            "",
        ]
        if not missing:
            lines.append("All checked meetings were ingested after they ended.")
        else:
            lines.append("## Possible gaps")
            lines.append("")
            lines.extend(missing)
        return "\n".join(lines).rstrip() + "\n"


def _looks_like_meeting(event: dict[str, Any]) -> bool:
    if event.get("attendees"):
        return True
    title = (event.get("summary") or "").lower()
    return any(w in title for w in ("sync", "standup", "1:1", "meeting", "review"))


def _event_day(event: dict[str, Any]) -> date:
    start = event.get("start") or {}
    raw = start.get("dateTime") or start.get("date") or ""
    if "T" in raw:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    if raw:
        return date.fromisoformat(raw[:10])
    return date.today()
