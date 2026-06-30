"""Attachment Router Agent — save Gmail attachments to the wiki volume.

Dispatched by gmail_manager at 8/12/4 workdays. Scans unhandled routing records
for messages with attachments and writes files under
``operations/gmail/attachments/`` by type (contracts, decks, documents).

SDK: Neither (deterministic REST fetch + wiki write).
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import attachments_dir, mailbox_id
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig, resolve_wiki_dir

SPECIALIST_KEY = "attachment_router"

CONTRACT_HINTS = ("contract", "msa", "nda", "agreement", "sow")
DECK_HINTS = ("deck", "pitch", "presentation", "slides")
DOC_HINTS = (".doc", ".docx", ".txt", ".md", ".rtf")


class AttachmentRouterAgent(BaseAgent):
    """Fetch attachments from triaged mail and store on the wiki volume."""

    name = "attachment_router"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return bool(self._pending())

    def run(self, **kwargs: Any) -> dict[str, Any]:
        saved = 0
        for record in self._pending():
            try:
                saved += self._route_message(record)
                self._store.mark_handled(record, SPECIALIST_KEY)
            except Exception:
                self.logger.exception("Attachment routing failed for %s", record.message_id)
        return {"attachments_saved": saved}

    def _pending(self):
        return self._store.unhandled_for(SPECIALIST_KEY, mailbox=self.mailbox)

    def _route_message(self, record) -> int:
        message = rest.get_message(record.message_id, mailbox=self.mailbox)
        attachments = rest.list_attachments(message)
        if not attachments:
            return 0

        count = 0
        base = resolve_wiki_dir() / attachments_dir()
        for att in attachments:
            data = rest.get_attachment(record.message_id, att["attachmentId"], mailbox=self.mailbox)
            subdir = self._subdir(att["filename"], att["mimeType"])
            safe_name = self._safe_filename(att["filename"], record.message_id)
            rel = PurePosixPath(attachments_dir()) / subdir / safe_name
            path = base / subdir / safe_name
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
            count += 1
            record.extracted.setdefault("attachments", []).append(str(rel))
        if count:
            self._store.write(record)
        return count

    @staticmethod
    def _subdir(filename: str, mime: str) -> str:
        lower = filename.lower()
        if any(h in lower for h in CONTRACT_HINTS):
            return "contracts"
        if any(h in lower for h in DECK_HINTS) or mime == "application/pdf" and "deck" in lower:
            return "decks"
        if lower.endswith(DOC_HINTS):
            return "documents"
        return "other"

    @staticmethod
    def _safe_filename(filename: str, message_id: str) -> str:
        stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", filename)[:120] or "attachment"
        return f"{message_id[:8]}_{stem}"
