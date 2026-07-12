"""Sync Pull — pull human Notion edits into the MD wiki (bidirectional page sync).

Detects Notion↔MD drift for bound pages, merges when compatible, preserves
human overrides under an unchanged agent signature, and marks hard conflicts
for Session 4 Conflict Resolutions.

SDK: Neither (Notion API via ``ntn`` + WikiStore).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.notion import db as notion_db
from company_brain.config import AppConfig
from company_brain.notion.client import NotionClient
from company_brain.notion.sync import NotionSync
from company_brain.notion.sync_policy import (
    SyncAction,
    body_hash,
    decide_pull_push,
    mark_sync_conflict,
    stamp_human_override,
)
from company_brain.notion.sync_routing import should_skip_notion_mirror
from company_brain.wiki.store import CONTROL_FILES, LocalWikiStore, MarkdownDoc, WikiStore


class SyncPullAgent(BaseAgent):
    """Pull Notion page edits into MD for pages with ``notion_page_id``."""

    name = "sync_pull"

    def __init__(
        self,
        config: AppConfig,
        *,
        store: WikiStore | None = None,
        client: NotionClient | None = None,
        **kwargs: Any,
    ):
        super().__init__(config, **kwargs)
        self._store = store or LocalWikiStore()
        self._client = client or NotionClient()

    def should_run(self, **kwargs: Any) -> bool:
        return notion_db.notion_is_available(self._client)

    def run(self, **kwargs: Any) -> dict[str, Any]:
        pulled = 0
        pushed = 0
        merged = 0
        conflicts = 0
        skipped = 0
        errors = 0

        for rel_path in self._store.list():
            name = rel_path.rsplit("/", 1)[-1]
            if name in CONTROL_FILES or not rel_path.endswith(".md"):
                continue
            try:
                outcome = self._sync_one(rel_path)
            except Exception:
                self.logger.exception("sync_pull failed for %s", rel_path)
                errors += 1
                continue
            if outcome == SyncAction.PULL:
                pulled += 1
            elif outcome == SyncAction.PUSH:
                pushed += 1
            elif outcome == SyncAction.MERGE:
                merged += 1
            elif outcome == SyncAction.CONFLICT:
                conflicts += 1
            else:
                skipped += 1

        return {
            "pulled": pulled,
            "pushed": pushed,
            "merged": merged,
            "conflicts": conflicts,
            "skipped": skipped,
            "errors": errors,
        }

    def _sync_one(self, rel_path: str) -> SyncAction:
        doc = self._store.read(rel_path)
        fm = dict(doc.frontmatter or {})
        page_id = str(fm.get("notion_page_id") or "").strip()
        if not page_id:
            return SyncAction.NOOP
        if should_skip_notion_mirror(fm, self.config):
            return SyncAction.NOOP

        try:
            notion_body, _edited = self._client.get_page_markdown(page_id)
        except Exception:
            self.logger.exception("Failed to fetch Notion page %s for %s", page_id, rel_path)
            raise

        synced_hash = fm.get("synced_hash")
        # Prefer normalized hash; also accept legacy content_hash equality via decide.
        decision = decide_pull_push(
            md_body=doc.body,
            notion_body=notion_body,
            synced_hash=str(synced_hash) if synced_hash else None,
        )
        now = datetime.now(timezone.utc).isoformat()

        if decision.action == SyncAction.NOOP:
            return SyncAction.NOOP

        if decision.action == SyncAction.PULL:
            self._write_pulled(rel_path, doc, notion_body, when_iso=now)
            return SyncAction.PULL

        if decision.action == SyncAction.PUSH:
            NotionSync(store=self._store, client=self._client, config=self.config).sync_doc(
                rel_path,
                force=False,
            )
            return SyncAction.PUSH

        if decision.action == SyncAction.MERGE and decision.merged_body is not None:
            self._write_body(rel_path, doc, decision.merged_body, when_iso=now, conflict=False)
            NotionSync(store=self._store, client=self._client, config=self.config).sync_doc(
                rel_path,
                force=True,
            )
            return SyncAction.MERGE

        # CONFLICT — mark frontmatter for Conflict Resolutions; do not overwrite either side.
        fm = mark_sync_conflict(fm, reason=decision.reason)
        fm["conflict_notion_body"] = notion_body
        fm["last_updated"] = now
        self._store.write(rel_path, MarkdownDoc(frontmatter=fm, body=doc.body))
        self.logger.warning("sync_pull conflict on %s (%s)", rel_path, decision.reason)
        return SyncAction.CONFLICT

    def _write_pulled(
        self,
        rel_path: str,
        doc: MarkdownDoc,
        notion_body: str,
        *,
        when_iso: str,
    ) -> None:
        fm = dict(doc.frontmatter or {})
        detail = f"Pulled human Notion edit at {when_iso}"
        if fm.get("pushed_agent_signature") or fm.get("agent_signature"):
            fm = stamp_human_override(fm, when_iso=when_iso, detail=detail)
        else:
            fm.pop("sync_conflict", None)
        fm["synced_hash"] = body_hash(notion_body)
        fm["last_synced"] = when_iso
        fm["last_updated"] = when_iso
        self._store.write(rel_path, MarkdownDoc(frontmatter=fm, body=notion_body))
        self.logger.info("Pulled Notion → MD for %s", rel_path)

    def _write_body(
        self,
        rel_path: str,
        doc: MarkdownDoc,
        body: str,
        *,
        when_iso: str,
        conflict: bool,
    ) -> None:
        fm = dict(doc.frontmatter or {})
        if conflict:
            fm = mark_sync_conflict(fm, reason="merge")
        else:
            fm.pop("sync_conflict", None)
        fm["synced_hash"] = body_hash(body)
        fm["last_synced"] = when_iso
        fm["last_updated"] = when_iso
        self._store.write(rel_path, MarkdownDoc(frontmatter=fm, body=body))
