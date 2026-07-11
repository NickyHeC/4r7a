"""Discord thread routing records (one JSON file per conversation on the wiki volume)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from company_brain.config import resolve_wiki_dir

ROUTING_DIR = "growth/discord/routing"


def _slug_id(value: str) -> str:
    ref = (value or "").strip()
    if ref.isdigit():
        return ref
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", ref) or "unknown"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DiscordRoutingRecord:
    channel_id: str
    thread_id: str
    created_at: str
    updated_at: str
    parent_channel_id: str = ""
    attention: str | None = None
    kind: str | None = None
    community: bool = True
    extracted: dict[str, Any] = field(default_factory=dict)
    handled: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiscordRoutingRecord:
        return cls(
            channel_id=str(data.get("channel_id") or ""),
            thread_id=str(data.get("thread_id") or ""),
            parent_channel_id=str(data.get("parent_channel_id") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            attention=data.get("attention"),
            kind=data.get("kind"),
            community=bool(data.get("community", True)),
            extracted=dict(data.get("extracted") or {}),
            handled=dict(data.get("handled") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DiscordRoutingStore:
    """Atomic JSON store for Discord conversation routing records."""

    def __init__(self, wiki_dir: Path | None = None):
        self._root = (wiki_dir or resolve_wiki_dir()) / ROUTING_DIR

    def _path(self, channel_id: str, thread_id: str) -> Path:
        return self._root / _slug_id(channel_id) / f"{_slug_id(thread_id)}.json"

    def read(self, channel_id: str, thread_id: str) -> DiscordRoutingRecord | None:
        path = self._path(channel_id, thread_id)
        if not path.exists():
            return None
        try:
            return DiscordRoutingRecord.from_dict(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError, KeyError):
            return None

    def write(self, record: DiscordRoutingRecord) -> None:
        record.updated_at = _utc_now()
        if not record.created_at:
            record.created_at = record.updated_at
        path = self._path(record.channel_id, record.thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True))
        tmp.replace(path)

    def upsert(
        self,
        channel_id: str,
        thread_id: str,
        **fields: Any,
    ) -> DiscordRoutingRecord:
        existing = self.read(channel_id, thread_id)
        if existing:
            data = existing.to_dict()
            data.update(fields)
            record = DiscordRoutingRecord.from_dict(data)
        else:
            now = _utc_now()
            record = DiscordRoutingRecord(
                channel_id=channel_id,
                thread_id=thread_id,
                created_at=now,
                updated_at=now,
                **fields,
            )
        self.write(record)
        return record

    def mark_handled(self, record: DiscordRoutingRecord, specialist_key: str) -> None:
        record.handled[specialist_key] = _utc_now()
        self.write(record)

    def iter_channel(self, channel_id: str) -> Iterable[DiscordRoutingRecord]:
        base = self._root / _slug_id(channel_id)
        if not base.is_dir():
            return
        for path in sorted(base.glob("*.json")):
            try:
                yield DiscordRoutingRecord.from_dict(json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError, KeyError):
                continue

    def iter_all(self) -> Iterable[DiscordRoutingRecord]:
        if not self._root.is_dir():
            return
        for path in sorted(self._root.rglob("*.json")):
            try:
                yield DiscordRoutingRecord.from_dict(json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError, KeyError):
                continue

    def iter_open(self, *, kind: str | None = None) -> Iterable[DiscordRoutingRecord]:
        if not self._root.is_dir():
            return
        for path in sorted(self._root.rglob("*.json")):
            try:
                record = DiscordRoutingRecord.from_dict(json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError, KeyError):
                continue
            if kind and record.kind != kind:
                continue
            if record.handled.get("closed"):
                continue
            yield record
