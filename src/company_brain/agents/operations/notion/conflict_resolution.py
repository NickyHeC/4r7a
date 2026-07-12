"""Conflict Resolution — evidence tie-break or enqueue hard wiki↔Notion conflicts.

Scans pages with ``sync_conflict``, gathers Slack/meeting/email-derived wiki
evidence, auto-applies when clearly favored, otherwise appends the Conflict
Resolutions log and mirrors a Notion DB row for admin judgment.

SDK: Neither (WikiStore + optional Notion DB).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.notion import conflict_store as store_mod
from company_brain.agents.operations.notion import db as notion_db
from company_brain.config import AppConfig
from company_brain.notion.client import NotionClient
from company_brain.notion.scoped_search import (
    COMPANY_PREFIXES,
    prefixes_for_teamspace,
    teamspace_key_for_page,
)
from company_brain.notion.sync import NotionSync
from company_brain.notion.sync_policy import SYNC_CONFLICT_KEY, body_hash
from company_brain.wiki.publish import APPEND, format_append_section, write_wiki_page
from company_brain.wiki.store import CONTROL_FILES, LocalWikiStore, MarkdownDoc, WikiStore


class ConflictResolutionAgent(BaseAgent):
    """Resolve or escalate pages marked ``sync_conflict``."""

    name = "conflict_resolution"
    WRITE_MODE = APPEND

    def __init__(
        self,
        config: AppConfig,
        *,
        store: WikiStore | None = None,
        client: NotionClient | None = None,
        sync: bool = True,
        **kwargs: Any,
    ):
        super().__init__(config, **kwargs)
        self._store = store or LocalWikiStore()
        self._client = client or NotionClient()
        self._sync = sync

    def should_run(self, **kwargs: Any) -> bool:
        return True

    def run(self, **kwargs: Any) -> dict[str, Any]:
        auto = 0
        escalated = 0
        for rel_path in list(self._store.list()):
            name = rel_path.rsplit("/", 1)[-1]
            if name in CONTROL_FILES:
                continue
            try:
                doc = self._store.read(rel_path)
            except FileNotFoundError:
                continue
            fm = dict(doc.frontmatter or {})
            reason = fm.get(SYNC_CONFLICT_KEY)
            if not reason:
                continue
            notion_body = self._fetch_notion(fm)
            outcome = self._handle(rel_path, doc, notion_body, str(reason))
            if outcome == "auto":
                auto += 1
            elif outcome == "escalated":
                escalated += 1
        return {"auto_resolved": auto, "escalated": escalated}

    def _fetch_notion(self, fm: dict[str, Any]) -> str:
        page_id = str(fm.get("notion_page_id") or "").strip()
        if not page_id or not notion_db.notion_is_available(self._client):
            return str(fm.get("conflict_notion_body") or "")
        try:
            body, _ = self._client.get_page_markdown(page_id)
            return body
        except Exception:
            self.logger.exception("Failed to fetch Notion body for conflict")
            return str(fm.get("conflict_notion_body") or "")

    def _handle(
        self,
        rel_path: str,
        doc: MarkdownDoc,
        notion_body: str,
        reason: str,
    ) -> str:
        fm = dict(doc.frontmatter or {})
        fm_ctx = dict(fm)
        fm_ctx["_rel_path"] = rel_path
        ts = teamspace_key_for_page(fm_ctx, self.config)
        prefixes = prefixes_for_teamspace(ts) if ts else list(COMPANY_PREFIXES)
        snippets = store_mod.gather_conflict_evidence(
            store=self._store,
            md_body=doc.body,
            notion_body=notion_body or "",
            prefixes=prefixes,
            exclude=rel_path,
        )
        winner = store_mod.evidence_winner(doc.body, notion_body or "", snippets)
        now = datetime.now(timezone.utc).isoformat()
        title = str(fm.get("title") or rel_path)

        if winner == "md":
            self._apply_body(rel_path, doc, doc.body, when=now, via="evidence_md")
            self._append_log(
                heading=f"{now[:10]} — auto {title}",
                body=(
                    f"**Path:** `{rel_path}`\n"
                    f"**Reason:** {reason}\n"
                    f"**Resolution:** kept MD (evidence)\n"
                    f"**Sources:** {len(snippets)} wiki snippets\n"
                ),
            )
            return "auto"

        if winner == "notion" and notion_body:
            self._apply_body(rel_path, doc, notion_body, when=now, via="evidence_notion")
            self._append_log(
                heading=f"{now[:10]} — auto {title}",
                body=(
                    f"**Path:** `{rel_path}`\n"
                    f"**Reason:** {reason}\n"
                    f"**Resolution:** kept Notion (evidence)\n"
                    f"**Sources:** {len(snippets)} wiki snippets\n"
                ),
            )
            return "auto"

        # Escalate — stash notion snapshot for apply agent; write log + DB row once.
        if not fm.get("conflict_enqueued"):
            fm["conflict_notion_body"] = notion_body
            fm["conflict_enqueued"] = True
            fm["last_updated"] = now
            self._store.write(rel_path, MarkdownDoc(frontmatter=fm, body=doc.body))
            row_id = ""
            if store_mod.notion_db_available(self._client):
                row_id = store_mod.create_conflict_row(
                    title=f"Conflict — {title}",
                    rel_path=rel_path,
                    reason=reason,
                    client=self._client,
                )
            self._append_log(
                heading=f"{now[:10]} — open {title}",
                body=(
                    f"**Path:** `{rel_path}`\n"
                    f"**Reason:** {reason}\n"
                    f"**Status:** awaiting admin\n"
                    f"**Notion row:** {row_id or '(none)'}\n"
                    f"**Evidence snippets:** {len(snippets)}\n"
                ),
            )
            return "escalated"
        return "skipped"

    def _apply_body(
        self,
        rel_path: str,
        doc: MarkdownDoc,
        body: str,
        *,
        when: str,
        via: str,
    ) -> None:
        fm = dict(doc.frontmatter or {})
        fm.pop(SYNC_CONFLICT_KEY, None)
        fm.pop("conflict_enqueued", None)
        fm.pop("conflict_notion_body", None)
        fm["synced_hash"] = body_hash(body)
        fm["last_synced"] = when
        fm["last_updated"] = when
        fm["conflict_resolved_via"] = via
        self._store.write(rel_path, MarkdownDoc(frontmatter=fm, body=body))
        if self._sync:
            try:
                NotionSync(store=self._store, client=self._client, config=self.config).sync_doc(
                    rel_path,
                    force=True,
                )
            except Exception:
                self.logger.exception("Notion sync failed after conflict resolve %s", rel_path)

    def _append_log(self, *, heading: str, body: str) -> None:
        section = format_append_section(heading, body, trigger="conflict_resolution")
        write_wiki_page(
            store_mod.WIKI_PATH,
            store_mod.TITLE,
            section,
            mode=APPEND,
            section="operations/notion",
            store=self._store,
            sync=self._sync,
        )
