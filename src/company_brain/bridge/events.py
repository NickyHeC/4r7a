"""Append-only bridge event ledger."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from company_brain.bridge.config import BridgeConfig, load_bridge_config


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SEVERITIES = frozenset({"critical", "high", "medium", "low"})


@dataclass
class BridgeEvent:
    event_id: str
    ts: str
    member: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    materialized: bool = False
    idempotency_key: str = ""

    @classmethod
    def create_blocker(
        cls,
        *,
        member: str,
        title: str,
        area: str,
        severity: str,
        blocked_since: str = "",
        evidence: str = "",
        suggested_owner: str = "",
        idempotency_key: str = "",
        event_id: str | None = None,
    ) -> BridgeEvent:
        sev = severity.strip().lower()
        if sev not in SEVERITIES:
            raise ValueError(f"invalid severity: {severity}")
        title = title.strip()[:200]
        area = area.strip()[:120]
        evidence = evidence.strip()[:500]
        if not title or not area:
            raise ValueError("title and area are required")
        return cls(
            event_id=event_id or str(uuid.uuid4()),
            ts=_utc_now(),
            member=member.strip(),
            event_type="blocker",
            payload={
                "title": title,
                "area": area,
                "severity": sev,
                "blocked_since": blocked_since.strip()[:32],
                "evidence": evidence,
                "suggested_owner": suggested_owner.strip()[:80],
            },
            idempotency_key=idempotency_key.strip(),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BridgeEvent:
        return cls(
            event_id=str(data["event_id"]),
            ts=str(data.get("ts") or ""),
            member=str(data.get("member") or ""),
            event_type=str(data.get("event_type") or ""),
            payload=dict(data.get("payload") or {}),
            materialized=bool(data.get("materialized")),
            idempotency_key=str(data.get("idempotency_key") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def title_hash(self) -> str:
        import hashlib

        raw = f"{self.member}:{self.payload.get('title', '')}:{self.payload.get('area', '')}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class BridgeEventStore:
    def __init__(self, cfg: BridgeConfig | None = None, config_dir: Path | None = None):
        self._cfg = cfg or load_bridge_config(config_dir)
        from company_brain.config import CONFIG_DIR

        self._dir = config_dir or CONFIG_DIR
        self._path = self._cfg.ledger_file(self._dir)

    def append(self, event: BridgeEvent) -> BridgeEvent:
        if self.get(event.event_id):
            return event
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        return event

    def list_all(self) -> list[BridgeEvent]:
        if not self._path.exists():
            return []
        out: list[BridgeEvent] = []
        for line in self._path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(BridgeEvent.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError):
                continue
        return out

    def get(self, event_id: str) -> BridgeEvent | None:
        ref = (event_id or "").strip()
        for event in self.list_all():
            if event.event_id == ref:
                return event
        return None

    def find_by_idempotency(self, member: str, key: str) -> BridgeEvent | None:
        ref = (key or "").strip()
        if not ref:
            return None
        for event in reversed(self.list_all()):
            if event.member == member and event.idempotency_key == ref:
                return event
        return None

    def list_unmaterialized(self) -> list[BridgeEvent]:
        return [e for e in self.list_all() if not e.materialized]

    def mark_materialized(self, event_id: str) -> BridgeEvent | None:
        events = self.list_all()
        updated: BridgeEvent | None = None
        for idx, event in enumerate(events):
            if event.event_id != event_id:
                continue
            event.materialized = True
            events[idx] = event
            updated = event
            break
        if updated is None:
            return None
        self._rewrite(events)
        return updated

    def _rewrite(self, events: list[BridgeEvent]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".jsonl.tmp")
        lines = [json.dumps(e.to_dict(), sort_keys=True) for e in events]
        tmp.write_text("\n".join(lines) + ("\n" if lines else ""))
        tmp.replace(self._path)
