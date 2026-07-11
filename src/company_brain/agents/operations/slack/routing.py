"""Slack thread routing records (one JSON file per thread on the wiki volume)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from company_brain.config import resolve_wiki_dir

ROUTING_DIR = "operations/slack/routing"


def _slug_channel(channel: str) -> str:
    ref = (channel or "").strip().lstrip("#")
    if ref.startswith("C") and len(ref) >= 9:
        return ref
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", ref) or "unknown"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SlackRoutingRecord:
    channel: str
    thread_ts: str
    created_at: str
    updated_at: str
    attention: str | None = None
    kind: str | None = None
    assignees: list[str] = field(default_factory=list)
    customer: bool = False
    extracted: dict[str, Any] = field(default_factory=dict)
    handled: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SlackRoutingRecord:
        return cls(
            channel=str(data.get("channel") or ""),
            thread_ts=str(data.get("thread_ts") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            attention=data.get("attention"),
            kind=data.get("kind"),
            assignees=[str(a) for a in (data.get("assignees") or [])],
            customer=bool(data.get("customer")),
            extracted=dict(data.get("extracted") or {}),
            handled=dict(data.get("handled") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SlackRoutingStore:
    """Atomic JSON store for Slack thread routing records."""

    def __init__(self, wiki_dir: Path | None = None):
        self._root = (wiki_dir or resolve_wiki_dir()) / ROUTING_DIR

    def _path(self, channel: str, thread_ts: str) -> Path:
        safe_ts = thread_ts.replace(".", "_")
        return self._root / _slug_channel(channel) / f"{safe_ts}.json"

    def read(self, channel: str, thread_ts: str) -> SlackRoutingRecord | None:
        path = self._path(channel, thread_ts)
        if not path.exists():
            return None
        try:
            return SlackRoutingRecord.from_dict(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError, KeyError):
            return None

    def write(self, record: SlackRoutingRecord) -> None:
        record.updated_at = _utc_now()
        if not record.created_at:
            record.created_at = record.updated_at
        path = self._path(record.channel, record.thread_ts)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True))
        tmp.replace(path)

    def upsert(
        self,
        channel: str,
        thread_ts: str,
        **fields: Any,
    ) -> SlackRoutingRecord:
        existing = self.read(channel, thread_ts)
        if existing:
            data = existing.to_dict()
            data.update(fields)
            record = SlackRoutingRecord.from_dict(data)
        else:
            now = _utc_now()
            record = SlackRoutingRecord(
                channel=channel,
                thread_ts=thread_ts,
                created_at=now,
                updated_at=now,
                **fields,
            )
        self.write(record)
        return record

    def mark_handled(self, record: SlackRoutingRecord, specialist_key: str) -> None:
        record.handled[specialist_key] = _utc_now()
        self.write(record)

    def iter_channel(self, channel: str) -> Iterable[SlackRoutingRecord]:
        base = self._root / _slug_channel(channel)
        if not base.is_dir():
            return
        for path in sorted(base.glob("*.json")):
            try:
                yield SlackRoutingRecord.from_dict(json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError, KeyError):
                continue

    def iter_open(self, *, kind: str | None = None) -> Iterable[SlackRoutingRecord]:
        if not self._root.is_dir():
            return
        for path in sorted(self._root.rglob("*.json")):
            try:
                record = SlackRoutingRecord.from_dict(json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError, KeyError):
                continue
            if kind and record.kind != kind:
                continue
            if record.handled.get("closed"):
                continue
            yield record
