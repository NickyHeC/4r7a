"""Granola Ingest Agent — meeting notes into the wiki.

Specialist dispatched by ``meeting_watch`` after a calendar meeting ends
(once per meeting day). Pulls Granola notes, writes raw entries for absorb, and
compiles a company-wide daily digest page.

Supports two deployment modes:
- **business** — one API key per member (personal-notes scope); roster in
  ``config/operations.yaml`` → ``granola.members``, keys in env.
- **enterprise** — single ``GRANOLA_API_KEY`` with public-notes scope for
  company-wide Team-space visibility.

SDK: Neither (deterministic REST extraction).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import is_handled, mark_handled
from company_brain.agents.operations.granola import granola_client as client
from company_brain.agents.operations.shared import granola_config as cfg
from company_brain.config import resolve_raw_dir
from company_brain.ingestion.entry import RawEntry
from company_brain.wiki.publish import write_wiki_page


class IngestAgent(BaseAgent):
    """Pull today's Granola notes and ingest at end of day."""

    name = "ingest"
    WRITE_MODE = "update"

    def run(
        self,
        *,
        once: bool = False,
        target_date: date | None = None,
        event_title: str | None = None,
        dispatch_task: bool = True,
        **kwargs: Any,
    ) -> Any:
        if once or target_date is not None or event_title is not None:
            return self.run_once(
                target_date=target_date,
                event_title=event_title,
                dispatch_task=dispatch_task,
            )
        from company_brain.agents.operations.granola.meeting_watch import (
            MeetingWatchAgent,
        )

        return MeetingWatchAgent(self.config).run(**kwargs)

    def run_once(
        self,
        *,
        target_date: date | None = None,
        event_title: str | None = None,
        dispatch_task: bool = True,
    ) -> dict[str, Any]:
        day = target_date or date.today()
        day_key = day.isoformat()
        if is_handled("ingest", day_key):
            return {"status": "already_handled", "date": day_key}

        if not cfg.granola_is_configured():
            self.logger.warning("Granola not configured — skipping ingest")
            return {"status": "not_configured", "date": day_key}

        summaries = self._collect_day_summaries(day)
        if event_title:
            summaries = _filter_by_event_title(summaries, event_title)
        if not summaries:
            mark_handled("ingest", day_key)
            return {"status": "empty", "date": day_key, "notes": 0}

        ingested = 0
        sections: list[str] = []
        ingested_notes: list[dict[str, Any]] = []
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
            ingested_notes.append(summary)
            sections.append(format_digest_section(detail, member_label=summary.get("member_label")))
            self._record_employee_work_event(
                note_id=note_id,
                meeting_date=day_key,
                detail=detail,
                member_label=summary.get("member_label"),
                wiki_path=cfg.daily_wiki_path(day_key),
            )

        digest_body = "\n\n".join(sections)
        wiki_path = cfg.daily_wiki_path(day_key)
        write_wiki_page(
            wiki_path,
            f"Meetings {day_key}",
            digest_body,
            mode=self.WRITE_MODE,
        )
        mark_handled("ingest", day_key)
        task_result = None
        if dispatch_task and ingested_notes:
            task_result = self._dispatch_tasks(ingested_notes, day_key)
        return {
            "status": "ok",
            "date": day_key,
            "notes": ingested,
            "wiki_path": wiki_path,
            "task": task_result,
        }

    def _dispatch_tasks(self, notes: list[dict[str, Any]], day_key: str) -> dict[str, Any]:
        from company_brain.agents.operations.granola.task import TaskAgent
        from company_brain.runtime import get_runtime

        return get_runtime().run(
            TaskAgent,
            self.config,
            notes=notes,
            meeting_date=day_key,
        )

    def _record_employee_work_event(
        self,
        *,
        note_id: str,
        meeting_date: str,
        detail: dict[str, Any],
        member_label: str | None,
        wiki_path: str,
    ) -> None:
        from company_brain.agents.employee_wiki.work_event_materializer import (
            record_granola_work_event,
        )
        from company_brain.agents.operations.granola.task import extract_action_items

        title = str(detail.get("title") or f"Meeting {note_id}")
        try:
            record_granola_work_event(
                note_id=note_id,
                meeting_date=meeting_date,
                title=title,
                member_label=member_label,
                detail=detail,
                action_item_count=len(extract_action_items(detail)),
                company_links=[wiki_path],
            )
        except Exception:
            self.logger.exception("Employee wiki Granola work event failed for %s", note_id)

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


def _filter_by_event_title(
    summaries: list[dict[str, Any]],
    event_title: str,
) -> list[dict[str, Any]]:
    """Match Granola notes to a calendar event title (best-effort)."""
    needle = event_title.strip().lower()
    if not needle:
        return summaries
    matched: list[dict[str, Any]] = []
    for summary in summaries:
        detail = summary.get("detail") or {}
        title = str(detail.get("title") or "").lower()
        cal = detail.get("calendar_event") or {}
        cal_title = str(cal.get("title") or "").lower()
        if needle in title or needle in cal_title or title in needle:
            matched.append(summary)
    return matched or summaries


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
