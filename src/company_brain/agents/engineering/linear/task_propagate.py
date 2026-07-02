"""Deterministic task status propagation with ledger and echo suppression."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.engineering.linear.task_bindings import (
    TaskBinding,
    TaskBindingStore,
    mirror_binding_to_wiki,
    rebuild_task_index,
)
from company_brain.wiki.store import WikiStore

SYSTEM_SOURCES = frozenset(
    {
        "system:linear_completed",
        "system:task_propagate",
    }
)

TERMINAL_LINEAR_STATUSES = frozenset({"done", "canceled", "cancelled"})
URGENT_FIELDS = frozenset({"status", "archived"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_system_source(source: str | None) -> bool:
    return (source or "") in SYSTEM_SOURCES


def is_terminal_linear_status(value: str) -> bool:
    return (value or "").strip().lower() in TERMINAL_LINEAR_STATUSES


def record_status_change(
    binding: TaskBinding,
    *,
    platform: str,
    field: str,
    value: Any,
    source: str | None = None,
    store: TaskBindingStore | None = None,
    wiki_store: WikiStore | None = None,
    sync_notion: bool = True,
    mirror_wiki: bool = True,
    propagate: bool = True,
) -> TaskBinding:
    """Append or update a status-track entry and persist the binding."""
    if _is_echo(binding, platform, field, source):
        return binding

    now = _utc_now()
    entry = {
        "platform": platform,
        "field": field,
        "value": value,
        "updated_at": now,
        "propagated_at": now if is_system_source(source) else None,
        "source": source or "",
    }
    _upsert_track_entry(binding, entry)
    store = store or TaskBindingStore()
    saved = store.upsert(
        binding,
        mirror_wiki=False,
        wiki_store=wiki_store,
        sync_notion=False,
    )
    if mirror_wiki:
        mirror_binding_to_wiki(saved, store=wiki_store, sync=sync_notion)
        rebuild_task_index(store.list_all(), store=wiki_store, sync=sync_notion)
    if propagate and platform == "linear" and field == "status":
        _fan_out_notion(saved, str(value))
    return saved


def _fan_out_notion(binding: TaskBinding, linear_status: str) -> None:
    """Push Linear status to the bound Notion task row when fan-out includes notion."""
    try:
        from company_brain.agents.operations.notion.task_sync import TaskSyncAgent
        from company_brain.config import load_config

        TaskSyncAgent(load_config()).run(
            binding=binding,
            linear_status=linear_status,
            create_if_missing=False,
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Notion fan-out failed for %s", binding.task_id)


def mark_propagated(
    binding: TaskBinding,
    *,
    platform: str,
    field: str,
    store: TaskBindingStore | None = None,
    wiki_store: WikiStore | None = None,
    sync_notion: bool = True,
) -> TaskBinding:
    """Set ``propagated_at`` on the latest matching track entry."""
    now = _utc_now()
    for entry in reversed(binding.status_track):
        if entry.get("platform") == platform and entry.get("field") == field:
            entry["propagated_at"] = now
            break
    store = store or TaskBindingStore()
    saved = store.upsert(binding, mirror_wiki=False, wiki_store=wiki_store, sync_notion=False)
    mirror_binding_to_wiki(saved, store=wiki_store, sync=sync_notion)
    return saved


def pending_propagations(binding: TaskBinding) -> list[dict[str, Any]]:
    """Entries whose value has not yet been pushed to all targets."""
    out: list[dict[str, Any]] = []
    for entry in binding.status_track:
        if entry.get("propagated_at"):
            continue
        if is_system_source(entry.get("source")):
            continue
        out.append(entry)
    return out


def should_propagate_field(binding: TaskBinding, platform: str, field: str, value: Any) -> bool:
    """Return False when an outbound write would echo an already-propagated state."""
    for entry in reversed(binding.status_track):
        if entry.get("platform") != platform or entry.get("field") != field:
            continue
        if entry.get("value") == value and entry.get("propagated_at"):
            return False
        break
    return True


def field_authority(platform: str, field: str, *, binding: TaskBinding | None = None) -> int:
    """Higher score wins conflicts for a field (stub — extend per platform rules)."""
    _ = binding
    if field == "status" and platform == "linear":
        return 100
    if field == "archived" and platform == "gmail":
        return 90
    if platform == (binding.origin.get("platform") if binding else ""):
        return 80
    return 50


def _upsert_track_entry(binding: TaskBinding, entry: dict[str, Any]) -> None:
    for idx, existing in enumerate(binding.status_track):
        plat = entry["platform"]
        fld = entry["field"]
        if existing.get("platform") == plat and existing.get("field") == fld:
            binding.status_track[idx] = entry
            return
    binding.status_track.append(entry)


def _is_echo(binding: TaskBinding, platform: str, field: str, source: str | None) -> bool:
    """Ignore inbound updates that duplicate a recent system-originated write."""
    if is_system_source(source):
        return False
    for entry in reversed(binding.status_track):
        if entry.get("platform") == platform and entry.get("field") == field:
            return is_system_source(entry.get("source")) and bool(entry.get("propagated_at"))
    return False
