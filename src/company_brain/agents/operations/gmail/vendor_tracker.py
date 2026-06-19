"""Vendor Tracker Agent — one wiki page per vendor.

``Vendor``-tagged mail → ``operations/gmail/vendors/<slug>.md`` with ops metadata
(contact, renewal comms). Finance cost/recurrence stays in subscription_audit.

SDK: Neither (deterministic wiki writes).
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import mailbox_id, vendors_dir
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.agents.operations.shared.wiki_crm import append_crm_entry, format_mail_section
from company_brain.config import AppConfig
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

SPECIALIST_KEY = "vendor_tracker"


class VendorTrackerAgent(BaseAgent):
    """Maintain per-vendor wiki pages from Vendor-tagged mail."""

    name = "gmail_vendor_tracker"
    WRITE_MODE = "append"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return bool(self._store.unhandled_for(
            SPECIALIST_KEY, mailbox=self.mailbox, domain_tag="Vendor",
        ))

    def run(self, **kwargs: Any) -> dict[str, Any]:
        updated = 0
        for record in self._store.unhandled_for(
            SPECIALIST_KEY, mailbox=self.mailbox, domain_tag="Vendor",
        ):
            try:
                message = rest.get_message(record.message_id, mailbox=self.mailbox)
                from_ = record.extracted.get("from") or rest.message_from(message)
                slug = _vendor_slug(from_)
                rel_path = str(PurePosixPath(vendors_dir()) / f"{slug}.md")
                self._ensure_vendor_page(rel_path, slug, from_)
                append_crm_entry(rel_path, f"Vendor — {slug}", format_mail_section(record, message))
                self._store.mark_handled(record, SPECIALIST_KEY)
                updated += 1
            except Exception:
                self.logger.exception("Vendor tracker failed for %s", record.message_id)
        return {"updated": updated}

    @staticmethod
    def _ensure_vendor_page(rel_path: str, slug: str, from_hdr: str) -> None:
        store = LocalWikiStore()
        if store.exists(rel_path):
            return
        body = (
            f"# Vendor — {slug}\n\n"
            f"**Primary contact:** {from_hdr}\n\n"
            "## Comms log\n\n"
            "_Renewal and billing comms appended below. Finance subscription "
            "costs live in finance/subscription-audit._\n"
        )
        write_wiki_page(rel_path, f"Vendor — {slug}", body, mode=UPDATE, section="operations/gmail")


def _vendor_slug(from_hdr: str) -> str:
    m = re.search(r"@([a-zA-Z0-9.-]+)", from_hdr)
    domain = m.group(1).lower() if m else from_hdr.lower()
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", domain)[:60] or "unknown"
