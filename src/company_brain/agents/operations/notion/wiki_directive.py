"""Wiki Directive — act on plain-text ``@wiki`` instructions in Notion/MD pages.

Fill and/or move **only the current page**. Autofill is teamspace-scoped.
External-facing pages (``external: true``) are not filled unless the directive
explicitly includes ``fill``. MD first, then NotionSync.

SDK: Neither (WikiStore + Notion sync).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.config import AppConfig
from company_brain.notion.relocate import relocate_page
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
            relocate_page(
                store=self._store,
                config=self.config,
                from_path=target_path,
                to_path=relocate_to,
                fm=fm,
                body=body,
                title=title,
                when=now,
                sync=self._sync,
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
