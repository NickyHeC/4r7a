"""Append-only work event ledger for employee/company materializers."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from company_brain.config import CONFIG_DIR


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkEvent:
    event_id: str
    ts: str
    source: str
    artifact_ref: str
    primary_member: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    contributors: list[str] = field(default_factory=list)
    materialized: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        source: str,
        artifact_ref: str,
        primary_member: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        contributors: list[str] | None = None,
        event_id: str | None = None,
    ) -> WorkEvent:
        return cls(
            event_id=event_id or str(uuid.uuid4()),
            ts=_utc_now(),
            source=source,
            artifact_ref=artifact_ref,
            primary_member=primary_member,
            event_type=event_type,
            payload=dict(payload or {}),
            contributors=list(contributors or []),
            materialized={"company": False, "employee": []},
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkEvent:
        return cls(
            event_id=str(data["event_id"]),
            ts=str(data.get("ts") or ""),
            source=str(data.get("source") or ""),
            artifact_ref=str(data.get("artifact_ref") or ""),
            primary_member=str(data.get("primary_member") or ""),
            event_type=str(data.get("event_type") or ""),
            payload=dict(data.get("payload") or {}),
            contributors=[str(c) for c in (data.get("contributors") or [])],
            materialized=dict(data.get("materialized") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorkEventStore:
    """JSONL append-only ledger at ``config/work_events.jsonl``."""

    def __init__(self, config_dir: Path | None = None):
        self._path = (config_dir or CONFIG_DIR) / "work_events.jsonl"

    def append(self, event: WorkEvent) -> WorkEvent:
        if self.get(event.event_id):
            return event
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        return event

    def list_all(self) -> list[WorkEvent]:
        if not self._path.exists():
            return []
        events: list[WorkEvent] = []
        for line in self._path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(WorkEvent.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError):
                continue
        return events

    def get(self, event_id: str) -> WorkEvent | None:
        ref = (event_id or "").strip()
        if not ref:
            return None
        for event in self.list_all():
            if event.event_id == ref:
                return event
        return None

    def find_by_artifact(self, artifact_ref: str) -> WorkEvent | None:
        ref = (artifact_ref or "").strip()
        if not ref:
            return None
        for event in reversed(self.list_all()):
            if event.artifact_ref == ref:
                return event
        return None

    def list_unmaterialized(self, *, target: str = "employee") -> list[WorkEvent]:
        out: list[WorkEvent] = []
        for event in self.list_all():
            mat = event.materialized or {}
            if target == "employee":
                members = mat.get("employee") or []
                if event.primary_member and event.primary_member not in members:
                    out.append(event)
            elif target == "company":
                if not mat.get("company"):
                    out.append(event)
        return out

    def mark_materialized(
        self,
        event_id: str,
        *,
        company: bool | None = None,
        employee_member: str | None = None,
    ) -> WorkEvent | None:
        events = self.list_all()
        updated: WorkEvent | None = None
        for idx, event in enumerate(events):
            if event.event_id != event_id:
                continue
            mat = dict(event.materialized or {})
            if company is not None:
                mat["company"] = company
            if employee_member:
                members = list(mat.get("employee") or [])
                if employee_member not in members:
                    members.append(employee_member)
                mat["employee"] = members
            event.materialized = mat
            events[idx] = event
            updated = event
            break
        if updated is None:
            return None
        self._rewrite(events)
        return updated

    def _rewrite(self, events: list[WorkEvent]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".jsonl.tmp")
        lines = [json.dumps(e.to_dict(), sort_keys=True) for e in events]
        tmp.write_text("\n".join(lines) + ("\n" if lines else ""))
        tmp.replace(self._path)
