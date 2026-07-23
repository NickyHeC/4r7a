"""Shared fleet pause + redeploy cue (cooperative; no force-kill).

State keys live in ``config/state.json`` via ``StateStore``:

- ``fleet:pause_requested`` / ``fleet:paused`` — edit window
- ``fleet:busy:{manager}`` — in-flight dispatch markers
- ``fleet:redeploy_requested`` — cue for next admin/coding-agent session
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from company_brain.agents.gates import StateStore

KEY_PAUSE_REQUESTED = "fleet:pause_requested"
KEY_PAUSED = "fleet:paused"
KEY_PAUSE_AT = "fleet:pause_requested_at"
KEY_BUSY_PREFIX = "fleet:busy:"
KEY_REDEPLOY = "fleet:redeploy_requested"

# Soft wait hint for console / skill (managers keep looping; no force-kill).
DEFAULT_PAUSE_TIMEOUT_MINUTES = 30


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _store(store: StateStore | None = None) -> StateStore:
    return store or StateStore()


def request_pause(*, store: StateStore | None = None, by: str = "") -> dict[str, Any]:
    """Ask managers to finish in-flight work and stop new dispatches."""
    store = _store(store)
    at = _utcnow().isoformat()
    store.set(KEY_PAUSE_REQUESTED, True)
    store.set(KEY_PAUSE_AT, at)
    if not any_busy(store=store):
        store.set(KEY_PAUSED, True)
    return snapshot(store=store, by=by)


def resume(*, store: StateStore | None = None, by: str = "") -> dict[str, Any]:
    """Clear pause flags so managers may dispatch again."""
    store = _store(store)
    store.set(KEY_PAUSE_REQUESTED, False)
    store.set(KEY_PAUSED, False)
    store.delete(KEY_PAUSE_AT)
    return snapshot(store=store, by=by)


def is_pause_requested(*, store: StateStore | None = None) -> bool:
    return bool(_store(store).get(KEY_PAUSE_REQUESTED))


def is_paused(*, store: StateStore | None = None) -> bool:
    return bool(_store(store).get(KEY_PAUSED))


def should_start_work(*, store: StateStore | None = None) -> bool:
    """False while pause is requested or the fleet is fully paused."""
    store = _store(store)
    if store.get(KEY_PAUSE_REQUESTED) or store.get(KEY_PAUSED):
        return False
    return True


def can_dispatch(*, store: StateStore | None = None) -> bool:
    """Managers call this before starting specialists."""
    return should_start_work(store=store)


def set_busy(manager: str, busy: bool, *, store: StateStore | None = None) -> None:
    store = _store(store)
    name = (manager or "").strip()
    if not name:
        return
    key = f"{KEY_BUSY_PREFIX}{name}"
    if busy:
        store.set(key, {"name": name, "at": _utcnow().isoformat()})
    else:
        store.delete(key)
    try_enter_paused(store=store)


def any_busy(*, store: StateStore | None = None) -> bool:
    store = _store(store)
    return bool(store.keys(prefix=KEY_BUSY_PREFIX))


def busy_managers(*, store: StateStore | None = None) -> list[str]:
    store = _store(store)
    names: list[str] = []
    for key in store.keys(prefix=KEY_BUSY_PREFIX):
        payload = store.get(key) or {}
        if isinstance(payload, dict) and payload.get("name"):
            names.append(str(payload["name"]))
        else:
            names.append(key.removeprefix(KEY_BUSY_PREFIX))
    return sorted(names)


def try_enter_paused(*, store: StateStore | None = None) -> bool:
    """If pause requested and nothing busy, flip ``fleet:paused``."""
    store = _store(store)
    if not store.get(KEY_PAUSE_REQUESTED):
        return bool(store.get(KEY_PAUSED))
    if any_busy(store=store):
        return False
    store.set(KEY_PAUSED, True)
    return True


@contextmanager
def dispatch_slot(manager: str, *, store: StateStore | None = None) -> Iterator[bool]:
    """Context manager: yield False if dispatch blocked; else mark busy around work."""
    store = _store(store)
    if not can_dispatch(store=store):
        try_enter_paused(store=store)
        yield False
        return
    set_busy(manager, True, store=store)
    try:
        yield True
    finally:
        set_busy(manager, False, store=store)


def manager_heartbeat_detail(*, store: StateStore | None = None) -> str:
    """Suggested heartbeat detail for persistent manager loop ticks."""
    store = _store(store)
    if store.get(KEY_PAUSED):
        return "paused"
    if store.get(KEY_PAUSE_REQUESTED):
        return "pause_requested"
    return "idle"


def request_redeploy(
    *,
    sha: str = "",
    pr_url: str = "",
    by: str = "",
    note: str = "",
    store: StateStore | None = None,
) -> dict[str, Any]:
    """Record that agent code changed and managers should be redeployed next session."""
    store = _store(store)
    payload = {
        "at": _utcnow().isoformat(),
        "sha": (sha or "").strip(),
        "pr_url": (pr_url or "").strip(),
        "by": (by or "").strip(),
        "note": (note or "").strip(),
    }
    store.set(KEY_REDEPLOY, payload)
    return payload


def redeploy_pending(*, store: StateStore | None = None) -> dict[str, Any] | None:
    raw = _store(store).get(KEY_REDEPLOY)
    return dict(raw) if isinstance(raw, dict) else None


def clear_redeploy(*, store: StateStore | None = None) -> None:
    _store(store).delete(KEY_REDEPLOY)


def redeploy_instructions(*, store: StateStore | None = None) -> str | None:
    """Human/skill-facing steps when a redeploy cue is set."""
    pending = redeploy_pending(store=store)
    if not pending:
        return None
    lines = [
        "Fleet redeploy cue is set. Before continuing other 4r7a work:",
        "1. Confirm the agent-code PR is merged (if any).",
        "2. `company-brain admin fleet pause` — wait until Status shows paused (no busy managers).",
        "3. Pull/restart the company 4r7a checkout and restart persistent managers.",
        "4. `company-brain admin fleet resume`",
        "5. `company-brain admin fleet clear-redeploy`",
    ]
    if pending.get("pr_url"):
        lines.append(f"PR: {pending['pr_url']}")
    if pending.get("sha"):
        lines.append(f"SHA: {pending['sha']}")
    if pending.get("note"):
        lines.append(f"Note: {pending['note']}")
    return "\n".join(lines)


def snapshot(*, store: StateStore | None = None, by: str = "") -> dict[str, Any]:
    store = _store(store)
    return {
        "pause_requested": bool(store.get(KEY_PAUSE_REQUESTED)),
        "paused": bool(store.get(KEY_PAUSED)),
        "pause_requested_at": store.get(KEY_PAUSE_AT) or "",
        "busy": busy_managers(store=store),
        "can_dispatch": can_dispatch(store=store),
        "redeploy": redeploy_pending(store=store),
        "by": by,
    }
