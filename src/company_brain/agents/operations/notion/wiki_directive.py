"""Wiki Directive — act on plain-text ``@wiki`` instructions in Notion/MD pages.

Fill and/or move **only the current page**. Autofill is teamspace-scoped.
External-facing pages (``external: true``) are not filled unless the directive
explicitly includes ``fill``. MD first, then NotionSync.

SDK: Neither (WikiStore + Notion sync).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.notion import platform_config
from company_brain.config import AppConfig
from company_brain.notion.scoped_search import (
    build_fill_section,
    prefixes_for_teamspace,
    search_scoped_snippets,
    teamspace_key_for_page,
)
from company_brain.notion.sync import NotionSync
from company_brain.notion.sync_policy import body_hash
from company_brain.notion.wiki_directive import extract_directives, has_wiki_directive
from company_brain.wiki.store import CONTROL_FILES, LocalWikiStore, MarkdownDoc, WikiStore


class WikiDirectiveAgent(BaseAgent):
    """Process ``@wiki`` directives found on wiki pages."""

    name = "wiki_directive"

    def __init__(
        self,
        config: AppConfig,
        *,
        store: WikiStore | None = None,
        sync: bool = True,
        **kwargs: Any,
    ):
        super().__init__(config, **kwargs)
        self._store = store or LocalWikiStore()
        self._sync = sync

    def should_run(self, **kwargs: Any) -> bool:
        return True

    def run(self, **kwargs: Any) -> dict[str, Any]:
        filled = 0
        moved = 0
        marked_external = 0
        skipped = 0
        for rel_path in list(self._store.list()):
            name = rel_path.rsplit("/", 1)[-1]
            if name in CONTROL_FILES:
                continue
            try:
                doc = self._store.read(rel_path)
            except FileNotFoundError:
                continue
            if not has_wiki_directive(doc.body):
                continue
            result = self._process(rel_path, doc)
            filled += int(result.get("filled") or 0)
            moved += int(result.get("moved") or 0)
            marked_external += int(result.get("marked_external") or 0)
            skipped += int(result.get("skipped") or 0)
        return {
            "filled": filled,
            "moved": moved,
            "marked_external": marked_external,
            "skipped": skipped,
        }

    def _process(self, rel_path: str, doc: MarkdownDoc) -> dict[str, int]:
        directives, cleaned = extract_directives(doc.body)
        if not directives:
            return {"skipped": 1}

        fm = dict(doc.frontmatter or {})
        body = cleaned
        title = str(fm.get("title") or rel_path.rsplit("/", 1)[-1].removesuffix(".md"))
        now = datetime.now(timezone.utc)
        stats = {"filled": 0, "moved": 0, "marked_external": 0, "skipped": 0}
        target_path = rel_path
        relocate_to: str | None = None

        for d in directives:
            if d.mark_external:
                fm["external"] = True
                stats["marked_external"] += 1

            if d.want_fill:
                if fm.get("external") and "fill" not in d.instruction.lower():
                    self.logger.info(
                        "Skip fill on external page %s without explicit fill",
                        rel_path,
                    )
                    stats["skipped"] += 1
                else:
                    body = self._apply_fill(target_path, fm, body, title, d.instruction)
                    stats["filled"] += 1

            if d.move_to and d.move_to != target_path:
                relocate_to = d.move_to

        fm["last_updated"] = now.isoformat()
        fm["synced_hash"] = body_hash(body)
        # Ensure heading
        if not body.lstrip().startswith("# "):
            body = f"# {title}\n\n{body.lstrip()}"

        if relocate_to:
            self._relocate(
                from_path=target_path,
                to_path=relocate_to,
                fm=fm,
                body=body,
                title=title,
                when=now,
            )
            stats["moved"] += 1
            target_path = relocate_to
        else:
            self._store.write(target_path, MarkdownDoc(frontmatter=fm, body=body))
            if self._sync:
                try:
                    NotionSync(store=self._store, config=self.config).sync_doc(target_path)
                except Exception:
                    self.logger.exception("Notion sync failed after @wiki on %s", target_path)

        return stats

    def _apply_fill(
        self,
        rel_path: str,
        fm: dict[str, Any],
        body: str,
        title: str,
        instruction: str,
    ) -> str:
        fm_ctx = dict(fm)
        fm_ctx["_rel_path"] = rel_path
        ts = teamspace_key_for_page(fm_ctx, self.config)
        prefixes = prefixes_for_teamspace(ts)
        snippets = search_scoped_snippets(
            instruction,
            store=self._store,
            prefixes=prefixes,
            exclude=rel_path,
        )
        section = build_fill_section(instruction, snippets)
        # Prepend fill section under title
        if body.lstrip().startswith("# "):
            lines = body.split("\n", 1)
            rest = lines[1].lstrip("\n") if len(lines) > 1 else ""
            return f"{lines[0]}\n\n{section}\n{rest}".rstrip() + "\n"
        return f"# {title}\n\n{section}\n{body.lstrip()}".rstrip() + "\n"

    def _relocate(
        self,
        *,
        from_path: str,
        to_path: str,
        fm: dict[str, Any],
        body: str,
        title: str,
        when: datetime,
    ) -> None:
        """Move page content to ``to_path`` and leave a stub at ``from_path``."""
        ttl = platform_config.stub_ttl_days()
        expires = (when + timedelta(days=ttl)).isoformat()
        new_fm = dict(fm)
        new_fm["title"] = title
        new_fm["section"] = str(PurePosixPath(to_path).parent)
        if new_fm["section"] == ".":
            new_fm["section"] = ""
        new_fm["last_updated"] = when.isoformat()
        new_fm["synced_hash"] = body_hash(body)
        new_fm.pop("stub", None)
        new_fm.pop("stub_target", None)
        new_fm.pop("stub_expires_at", None)
        # Mark for page_system Notion parent fix if needed
        new_fm["relocated_from"] = from_path

        self._store.write(to_path, MarkdownDoc(frontmatter=new_fm, body=body))

        stub_title = f"Moved — {title}"
        stub_body = (
            f"# {stub_title}\n\n"
            f"This page moved to [[{to_path.removesuffix('.md')}]].\n\n"
            f"Stub expires {expires[:10]}.\n"
        )
        stub_section = str(PurePosixPath(from_path).parent)
        stub_fm = {
            "title": stub_title,
            "type": "stub",
            "stub": True,
            "stub_target": to_path,
            "stub_expires_at": expires,
            "section": "" if stub_section == "." else stub_section,
            "created": when.isoformat(),
            "last_updated": when.isoformat(),
        }
        # Keep old Notion binding on stub briefly so humans still land somewhere;
        # new page gets a fresh sync discover-or-create.
        if fm.get("notion_page_id"):
            # Transfer binding to the new page; stub is MD-only redirect.
            new_doc = self._store.read(to_path)
            nfm = dict(new_doc.frontmatter)
            nfm["notion_page_id"] = fm["notion_page_id"]
            self._store.write(to_path, MarkdownDoc(frontmatter=nfm, body=new_doc.body))

        self._store.write(from_path, MarkdownDoc(frontmatter=stub_fm, body=stub_body))

        if self._sync:
            try:
                NotionSync(store=self._store, config=self.config).sync_doc(to_path, force=True)
            except Exception:
                self.logger.exception("Notion sync failed after move to %s", to_path)
