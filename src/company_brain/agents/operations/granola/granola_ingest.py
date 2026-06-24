"""Granola Ingest Agent — daily end-of-day meeting notes into the wiki.

Persistent agent (no manager): every workday at 6pm, pulls Granola notes from
meetings that happened that day, writes raw entries for absorb, and compiles a
company-wide daily digest page.

Supports two deployment modes:
- **business** — one API key per member (personal-notes scope); roster in
  ``config/operations.yaml`` → ``granola.members``, keys in env.
- **enterprise** — single ``GRANOLA_API_KEY`` with public-notes scope for
  company-wide Team-space visibility.

SDK: Neither (deterministic REST extraction).
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import is_handled, mark_handled
from company_brain.agents.operations.granola import granola_client as client
from company_brain.agents.operations.shared import granola_config as cfg
from company_brain.agents.operations.shared.scheduling import (
    is_workday,
    next_daily_times,
)
from company_brain.config import resolve_raw_dir
from company_brain.ingestion.entry import RawEntry
from company_brain.wiki.publish import write_wiki_page


class GranolaIngestAgent(BaseAgent):
    """Pull today's Granola notes and ingest at end of day."""

    name = "granola_ingest"
    WRITE_MODE = "update"

    def run(self, *, once: bool = False, target_date: date | None = None, **kwargs: Any) -> Any:
        if once or target_date is not None:
            return self.run_once(target_date=target_date)
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        scheduled = cfg.ingest_time()
        self.logger.info(
            "Granola ingest starting persistent loop (daily at %02d:%02d)",
            scheduled.hour,
            scheduled.minute,
        )
        while True:
            now = datetime.now()
            if self._should_run_today(now):
                try:
                    self.run_once()
                except Exception:
                    self.logger.exception("Granola ingest run failed")
            nxt = next_daily_times(
                datetime.now(),
                [cfg.ingest_time()],
                workdays_only=cfg.workdays_only(),
            )
            wait = (nxt - datetime.now()).total_seconds()
            self.logger.info("Next Granola ingest at %s (sleep %.0fs)", nxt.isoformat(), wait)
            await asyncio.sleep(max(wait, 1))

    def _should_run_today(self, now: datetime) -> bool:
        if cfg.workdays_only() and not is_workday(now):
            return False
        scheduled = cfg.ingest_time()
        today_at = now.replace(
            hour=scheduled.hour, minute=scheduled.minute, second=0, microsecond=0,
        )
        if now < today_at:
            return False
        return not is_handled("granola_ingest", now.date().isoformat())

    def run_once(self, *, target_date: date | None = None) -> dict[str, Any]:
        day = target_date or date.today()
        day_key = day.isoformat()
        if is_handled("granola_ingest", day_key):
            return {"status": "already_handled", "date": day_key}

        if not cfg.granola_is_configured():
            self.logger.warning("Granola not configured — skipping ingest")
            return {"status": "not_configured", "date": day_key}

        summaries = self._collect_day_summaries(day)
        if not summaries:
            mark_handled("granola_ingest", day_key)
            return {"status": "empty", "date": day_key, "notes": 0}

        ingested = 0
        sections: list[str] = []
        for summary in summaries:
            note_id = summary["note_id"]
            if is_handled(f"granola_note:{day_key}", note_id):
                continue
            detail = summary.get("detail") or {}
            body = format_note_body(detail, member_label=summary.get("member_label"))
            entry = RawEntry(
                source_type="granola",
                source_id=note_id,
                title=detail.get("title") or f"Meeting {note_id}",
                content=body,
                metadata={
                    "granola_note_id": note_id,
                    "member_label": summary.get("member_label"),
                    "owner": detail.get("owner"),
                    "calendar_event": detail.get("calendar_event"),
                    "ingest_date": day_key,
                },
                tags=["granola", "meeting"],
            )
            _persist_raw_entry(entry)
            mark_handled(f"granola_note:{day_key}", note_id)
            ingested += 1
            sections.append(format_digest_section(detail, member_label=summary.get("member_label")))

        digest_body = "\n\n".join(sections)
        wiki_path = cfg.daily_wiki_path(day_key)
        write_wiki_page(
            wiki_path,
            f"Meeting notes — {day_key}",
            digest_body,
            mode=self.WRITE_MODE,
        )
        mark_handled("granola_ingest", day_key)
        return {
            "status": "ok",
            "date": day_key,
            "notes": ingested,
            "wiki_path": wiki_path,
        }

    def _collect_day_summaries(self, day: date) -> list[dict[str, Any]]:
        mode = cfg.granola_mode()
        if mode == "enterprise":
            return self._fetch_for_key(cfg.enterprise_api_key(), member_label=None, day=day)
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for label, _email, api_key in cfg.member_api_keys():
            for item in self._fetch_for_key(api_key, member_label=label, day=day):
                if item["note_id"] in seen:
                    continue
                seen.add(item["note_id"])
                out.append(item)
        return out

    def _fetch_for_key(
        self, api_key: str, *, member_label: str | None, day: date,
    ) -> list[dict[str, Any]]:
        if not api_key:
            return []
        summaries: list[dict[str, Any]] = []
        try:
            listed = client.list_notes_for_day(api_key, day)
        except client.GranolaAPIError as exc:
            label = member_label or "enterprise"
            self.logger.warning("Granola list failed for %s: %s", label, exc)
            return []

        for stub in listed:
            note_id = stub.get("id")
            if not note_id:
                continue
            try:
                detail = client.get_note(api_key, note_id, include_transcript=True)
            except client.GranolaAPIError as exc:
                self.logger.warning("Granola get_note failed for %s: %s", note_id, exc)
                continue
            summaries.append({
                "note_id": note_id,
                "member_label": member_label,
                "detail": detail,
            })
        return summaries


def format_note_body(note: dict[str, Any], *, member_label: str | None = None) -> str:
    """Markdown body for a raw entry."""
    lines = [_note_header(note, member_label=member_label), ""]
    summary = note.get("summary_markdown") or note.get("summary") or note.get("summary_text")
    if summary:
        lines.extend(["## Summary", "", str(summary).strip(), ""])
    transcript = note.get("transcript")
    if transcript:
        lines.extend(["## Transcript", ""])
        lines.extend(_format_transcript(transcript))
    return "\n".join(lines).strip() + "\n"


def format_digest_section(note: dict[str, Any], *, member_label: str | None = None) -> str:
    title = note.get("title") or "Untitled meeting"
    header = _note_header(note, member_label=member_label)
    summary = note.get("summary_markdown") or note.get("summary") or note.get("summary_text") or ""
    return f"## {title}\n\n{header}\n\n{str(summary).strip()}"


def _note_header(note: dict[str, Any], *, member_label: str | None = None) -> str:
    parts: list[str] = []
    if member_label:
        parts.append(f"- Member key: {member_label}")
    owner = note.get("owner") or {}
    if owner.get("name") or owner.get("email"):
        parts.append(f"- Owner: {owner.get('name', '')} <{owner.get('email', '')}>".strip())
    attendees = note.get("attendees") or []
    if attendees:
        names = []
        for person in attendees:
            if isinstance(person, dict):
                label = person.get("name") or person.get("email") or ""
                if label:
                    names.append(label)
            elif person:
                names.append(str(person))
        if names:
            parts.append(f"- Attendees: {', '.join(names)}")
    event = note.get("calendar_event") or {}
    if event.get("title") or event.get("start_time"):
        when = event.get("start_time") or event.get("start") or ""
        parts.append(f"- Calendar: {event.get('title', 'Meeting')} {when}".strip())
    note_id = note.get("id")
    if note_id:
        parts.append(f"- Granola ID: `{note_id}`")
    return "\n".join(parts)


def _format_transcript(transcript: list[Any]) -> list[str]:
    lines: list[str] = []
    for segment in transcript:
        if not isinstance(segment, dict):
            continue
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        speaker = segment.get("speaker") or {}
        if isinstance(speaker, dict):
            name = speaker.get("name") or speaker.get("source") or "Speaker"
        else:
            name = str(speaker)
        lines.append(f"**{name}:** {text}")
    return lines


def _persist_raw_entry(entry: RawEntry) -> None:
    entries_dir = resolve_raw_dir() / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)
    path = entries_dir / entry.filename()
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(entry.to_doc().serialize())
    tmp.replace(path)
