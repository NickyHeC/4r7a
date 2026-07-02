"""Ingestion pipeline: orchestrates running ingestors and deduplicating entries.

Raw entries are persisted as Markdown files (``raw/entries/{date}_{id}.md``)
with YAML frontmatter, following the wiki-gen skill. The absorb log lives with
the wiki control files (``<wiki>/_absorb_log.json``).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from company_brain.config import resolve_raw_dir, resolve_wiki_dir
from company_brain.ingestion.base import BaseIngestor
from company_brain.ingestion.entry import RawEntry
from company_brain.wiki.store import MarkdownDoc

logger = logging.getLogger(__name__)

ABSORB_LOG_FILE = "_absorb_log.json"


class IngestionPipeline:
    """Orchestrates ingestors and manages the raw entry store."""

    def __init__(self, project_root: Path | None = None):
        self._root = project_root
        self._entries_dir = resolve_raw_dir() / "entries"
        self._absorb_log_path = resolve_wiki_dir() / ABSORB_LOG_FILE
        self._ingestors: dict[str, BaseIngestor] = {}

    def register(self, ingestor: BaseIngestor) -> None:
        self._ingestors[ingestor.name] = ingestor

    def get_ingestor(self, name: str) -> BaseIngestor | None:
        return self._ingestors.get(name)

    @property
    def registered_sources(self) -> list[str]:
        return list(self._ingestors.keys())

    def run(self, source: str | None = None, **kwargs: Any) -> list[RawEntry]:
        """Run one or all registered ingestors.

        Returns the list of new (non-duplicate) entries.
        """
        targets = (
            [self._ingestors[source]]
            if source and source in self._ingestors
            else list(self._ingestors.values())
        )

        if not targets:
            logger.warning("No ingestors registered%s", f" for '{source}'" if source else "")
            return []

        all_entries: list[RawEntry] = []
        for ingestor in targets:
            try:
                entries = ingestor.ingest(**kwargs)
                all_entries.extend(entries)
            except Exception:
                logger.exception("Ingestion failed for %s", ingestor.name)

        new_entries = self._deduplicate(all_entries)
        self._persist_entries(new_entries)

        logger.info(
            "Pipeline complete: %d total, %d new entries", len(all_entries), len(new_entries)
        )
        return new_entries

    def load_unabsorbed(self) -> list[RawEntry]:
        """Load all entries that haven't been absorbed yet."""
        entries = self._load_all_entries()
        return [e for e in entries if not e.absorbed]

    def load_entries_since(self, since: datetime) -> list[RawEntry]:
        """Load unabsorbed entries newer than the given datetime."""
        entries = self.load_unabsorbed()
        return [e for e in entries if e.timestamp >= since]

    def mark_absorbed(self, entry_ids: list[str], article_ids: list[str]) -> None:
        """Mark entries as absorbed into specific articles (log + entry frontmatter)."""
        log = self._load_absorb_log()
        timestamp = datetime.now(timezone.utc).isoformat()
        for eid in entry_ids:
            log[eid] = {"absorbed_into": article_ids, "absorbed_at": timestamp}
            self._flag_entry_absorbed(eid, article_ids)
        self._save_absorb_log(log)

    def _flag_entry_absorbed(self, entry_id: str, article_ids: list[str]) -> None:
        if not self._entries_dir.exists():
            return
        for path in self._entries_dir.glob(f"*_{entry_id}.md"):
            entry = RawEntry.from_doc(MarkdownDoc.parse(path.read_text()))
            entry.mark_absorbed(article_ids)
            tmp = path.with_suffix(".md.tmp")
            tmp.write_text(entry.to_doc().serialize())
            tmp.replace(path)

    # -- Internal helpers -----------------------------------------------------

    def _deduplicate(self, entries: list[RawEntry]) -> list[RawEntry]:
        existing_ids = {e.id for e in self._load_all_entries()}
        return [e for e in entries if e.id not in existing_ids]

    def _persist_entries(self, entries: list[RawEntry]) -> None:
        self._entries_dir.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            path = self._entries_dir / entry.filename()
            tmp = path.with_suffix(".md.tmp")
            tmp.write_text(entry.to_doc().serialize())
            tmp.replace(path)

    def _load_all_entries(self) -> list[RawEntry]:
        if not self._entries_dir.exists():
            return []
        entries = []
        for path in sorted(self._entries_dir.glob("*.md")):
            entries.append(RawEntry.from_doc(MarkdownDoc.parse(path.read_text())))
        return entries

    def _load_absorb_log(self) -> dict[str, Any]:
        if not self._absorb_log_path.exists():
            return {}
        with open(self._absorb_log_path) as f:
            return json.load(f)

    def _save_absorb_log(self, log: dict[str, Any]) -> None:
        self._absorb_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._absorb_log_path, "w") as f:
            json.dump(log, f, indent=2)
