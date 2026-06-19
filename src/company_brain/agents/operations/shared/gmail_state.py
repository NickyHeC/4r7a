"""Per-mailbox Gmail cursor state on the wiki volume (shared across VMs)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from company_brain.config import resolve_wiki_dir

logger = logging.getLogger(__name__)

STATE_REL = "operations/gmail/_state.json"


def _slug(mailbox: str) -> str:
    if mailbox == "me":
        return "me"
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", mailbox)


class GmailState:
    """Persist historyId and agent markers per mailbox."""

    def __init__(self, path: Path | None = None):
        self._path = path or (resolve_wiki_dir() / STATE_REL)

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"mailboxes": {}}
        try:
            return json.loads(self._path.read_text()) or {"mailboxes": {}}
        except (OSError, json.JSONDecodeError):
            return {"mailboxes": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.replace(self._path)

    def _mb(self, mailbox: str) -> dict[str, Any]:
        data = self._load()
        mailboxes = data.setdefault("mailboxes", {})
        key = _slug(mailbox)
        return mailboxes.setdefault(key, {"mailbox": mailbox})

    def get_history_id(self, mailbox: str) -> str | None:
        val = self._mb(mailbox).get("history_id")
        return str(val) if val else None

    def set_history_id(self, mailbox: str, history_id: str) -> None:
        data = self._load()
        mb = data.setdefault("mailboxes", {}).setdefault(_slug(mailbox), {"mailbox": mailbox})
        mb["history_id"] = str(history_id)
        self._save(data)

    def get_sent_history_id(self, mailbox: str) -> str | None:
        val = self._mb(mailbox).get("sent_history_id")
        return str(val) if val else None

    def set_sent_history_id(self, mailbox: str, history_id: str) -> None:
        data = self._load()
        mb = data.setdefault("mailboxes", {}).setdefault(_slug(mailbox), {"mailbox": mailbox})
        mb["sent_history_id"] = str(history_id)
        self._save(data)

    def get(self, mailbox: str, key: str) -> Any:
        return self._mb(mailbox).get(key)

    def set(self, mailbox: str, key: str, value: Any) -> None:
        data = self._load()
        mb = data.setdefault("mailboxes", {}).setdefault(_slug(mailbox), {"mailbox": mailbox})
        mb[key] = value
        self._save(data)
