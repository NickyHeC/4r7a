"""Gmail triage routing records (one JSON file per message on the wiki volume)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from company_brain.config import resolve_wiki_dir

ROUTING_DIR = "operations/gmail/routing"


def _slug_mailbox(mailbox: str) -> str:
    if mailbox == "me":
        return "me"
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", mailbox)


@dataclass
class RoutingRecord:
    message_id: str
    thread_id: str
    mailbox: str
    triaged_at: str
    attention: str | None = None
    domain_tags: list[str] = field(default_factory=list)
    contact_type: str | None = None
    extracted: dict[str, Any] = field(default_factory=dict)
    handled: dict[str, str] = field(default_factory=dict)
    disposition: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoutingRecord:
        return cls(
            message_id=data["message_id"],
            thread_id=data.get("thread_id", ""),
            mailbox=data.get("mailbox", "me"),
            triaged_at=data.get("triaged_at", ""),
            attention=data.get("attention"),
            domain_tags=list(data.get("domain_tags") or []),
            contact_type=data.get("contact_type"),
            extracted=dict(data.get("extracted") or {}),
            handled=dict(data.get("handled") or {}),
            disposition=dict(data.get("disposition") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RoutingStore:
    def __init__(self, wiki_dir: Path | None = None):
        self._root = (wiki_dir or resolve_wiki_dir()) / ROUTING_DIR

    def _path(self, mailbox: str, message_id: str) -> Path:
        return self._root / _slug_mailbox(mailbox) / f"{message_id}.json"

    def exists(self, mailbox: str, message_id: str) -> bool:
        return self._path(mailbox, message_id).exists()

    def read(self, mailbox: str, message_id: str) -> RoutingRecord | None:
        path = self._path(mailbox, message_id)
        if not path.exists():
            return None
        try:
            return RoutingRecord.from_dict(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError, KeyError):
            return None

    def write(self, record: RoutingRecord) -> None:
        path = self._path(record.mailbox, record.message_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True))
        tmp.replace(path)

    def iter_mailbox(self, mailbox: str) -> Iterable[RoutingRecord]:
        dir_ = self._root / _slug_mailbox(mailbox)
        if not dir_.exists():
            return
        for path in sorted(dir_.glob("*.json")):
            try:
                yield RoutingRecord.from_dict(json.loads(path.read_text()))
            except (json.JSONDecodeError, KeyError):
                continue

    def unhandled_for(
        self,
        specialist_key: str,
        *,
        mailbox: str | None = None,
        attention: str | None = None,
        domain_tag: str | None = None,
    ) -> list[RoutingRecord]:
        """Records not yet handled by ``specialist_key``, optionally filtered."""
        out: list[RoutingRecord] = []
        if mailbox:
            records = self.iter_mailbox(mailbox)
        else:
            records = (
                rec
                for sub in self._root.iterdir()
                if sub.is_dir()
                for rec in self.iter_mailbox(sub.name)
            )
        for rec in records:
            if specialist_key in rec.handled:
                continue
            if specialist_key != "duplicate_across_mailboxes" and rec.extracted.get("duplicate_of"):
                continue
            if attention and rec.attention != attention:
                continue
            if domain_tag and domain_tag not in rec.domain_tags:
                continue
            out.append(rec)
        return out

    def unhandled_with_any_tag(
        self,
        specialist_key: str,
        tags: set[str],
        *,
        mailbox: str,
        exclude_contact_type: str | None = None,
    ) -> list[RoutingRecord]:
        out: list[RoutingRecord] = []
        for rec in self.iter_mailbox(mailbox):
            if specialist_key in rec.handled:
                continue
            if specialist_key != "duplicate_across_mailboxes" and rec.extracted.get("duplicate_of"):
                continue
            if exclude_contact_type and rec.contact_type == exclude_contact_type:
                continue
            if not tags.intersection(rec.domain_tags):
                continue
            out.append(rec)
        return out

    def mark_handled(self, record: RoutingRecord, specialist_key: str) -> None:
        record.handled[specialist_key] = datetime.now(timezone.utc).isoformat()
        self.write(record)

    def find_by_thread(self, mailbox: str, thread_id: str) -> list[RoutingRecord]:
        return [r for r in self.iter_mailbox(mailbox) if r.thread_id == thread_id]

    def upsert_thread_tags(
        self,
        mailbox: str,
        thread_id: str,
        *,
        add_tags: list[str] | None = None,
        extracted: dict[str, Any] | None = None,
    ) -> list[RoutingRecord]:
        """Merge domain tags / extracted fields onto every record in a thread."""
        updated: list[RoutingRecord] = []
        for rec in self.find_by_thread(mailbox, thread_id):
            for tag in add_tags or []:
                if tag not in rec.domain_tags:
                    rec.domain_tags.append(tag)
            if extracted:
                rec.extracted.update(extracted)
            self.write(rec)
            updated.append(rec)
        return updated


def new_record(
    *,
    message_id: str,
    thread_id: str,
    mailbox: str,
    attention: str | None,
    domain_tags: list[str],
    contact_type: str | None = None,
    extracted: dict[str, Any] | None = None,
    disposition: dict[str, Any] | None = None,
) -> RoutingRecord:
    return RoutingRecord(
        message_id=message_id,
        thread_id=thread_id,
        mailbox=mailbox,
        triaged_at=datetime.now(timezone.utc).isoformat(),
        attention=attention,
        domain_tags=domain_tags,
        contact_type=contact_type,
        extracted=extracted or {},
        disposition=disposition or {},
    )
