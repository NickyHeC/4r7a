"""Archive and stale-page eligibility policy (Session 6).

Archive only when **all** hold:
1. No MD edits for ``archive_idle_days``
2. Explicit ``status: done`` or past ``end_date``
3. No Notion edits for ``archive_idle_days``
4. No shared link confirmed (fail closed when unknown)

Stale review: active pages (not archive-eligible) idle past ``stale_idle_days``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any


@dataclass(frozen=True)
class ArchiveEligibility:
    eligible: bool
    reasons: tuple[str, ...]


def parse_iso(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_done(fm: dict[str, Any], *, now: datetime | None = None) -> bool:
    """True when status is done/complete or end_date is in the past."""
    now = now or datetime.now(timezone.utc)
    status = str(fm.get("status") or "").strip().lower()
    if status in {"done", "complete", "completed", "archived", "closed"}:
        return True
    end_raw = str(fm.get("end_date") or fm.get("ends") or "").strip()
    if not end_raw:
        return False
    # Accept YYYY-MM-DD or full ISO
    try:
        if len(end_raw) >= 10 and end_raw[4] == "-":
            end_d = date.fromisoformat(end_raw[:10])
            return end_d <= now.date()
    except ValueError:
        pass
    end_dt = parse_iso(end_raw)
    return bool(end_dt and end_dt <= now)


def md_idle(fm: dict[str, Any], *, idle_days: int, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    updated = parse_iso(str(fm.get("last_updated") or fm.get("created") or ""))
    if not updated:
        return False
    return (now - updated).days >= idle_days


def notion_idle(
    last_edited: str | None,
    *,
    idle_days: int,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(timezone.utc)
    edited = parse_iso(last_edited)
    if not edited:
        return False
    return (now - edited).days >= idle_days


def no_shared_link_confirmed(
    fm: dict[str, Any],
    notion_meta: dict[str, Any] | None = None,
) -> bool:
    """Fail closed: only True when we can confirm there is no shared link."""
    if fm.get("shared_link") is True:
        return False
    if fm.get("shared_link") is False:
        return True
    meta = notion_meta or {}
    if meta.get("public_url"):
        return False
    # Explicit admin/frontmatter opt-in when API cannot confirm
    if fm.get("no_shared_link") is True:
        return True
    return False


def archive_eligibility(
    fm: dict[str, Any],
    *,
    notion_last_edited: str | None,
    notion_meta: dict[str, Any] | None = None,
    idle_days: int = 30,
    now: datetime | None = None,
) -> ArchiveEligibility:
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    if not md_idle(fm, idle_days=idle_days, now=now):
        reasons.append("md_recent")
    if not is_done(fm, now=now):
        reasons.append("not_done")
    if not notion_idle(notion_last_edited, idle_days=idle_days, now=now):
        reasons.append("notion_recent_or_unknown")
    if not no_shared_link_confirmed(fm, notion_meta):
        reasons.append("shared_link_or_unknown")
    if fm.get("stub"):
        reasons.append("stub")
    if fm.get("archived"):
        reasons.append("already_archived")
    return ArchiveEligibility(eligible=not reasons, reasons=tuple(reasons))


def is_stale_candidate(
    fm: dict[str, Any],
    *,
    stale_days: int = 90,
    now: datetime | None = None,
) -> bool:
    """Active (not done) pages idle past stale_days — conflict-adjacent review."""
    now = now or datetime.now(timezone.utc)
    if fm.get("stub") or fm.get("archived"):
        return False
    if is_done(fm, now=now):
        return False
    if fm.get("stale_reviewed"):
        return False
    return md_idle(fm, idle_days=stale_days, now=now)
