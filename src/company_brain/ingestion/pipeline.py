"""Ingestion pipeline: orchestrates running ingestors and deduplicating entries."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from company_brain.ingestion.base import BaseIngestor
from company_brain.ingestion.entry import RawEntry

logger = logging.getLogger(__name__)

ENTRIES_DIR = "raw/entries"
ABSORB_LOG = "raw/absorb_log.json"


class IngestionPipeline:
    """Orchestrates ingestors and manages the raw entry store."""

    def __init__(self, project_root: Path):
        self._root = project_root
        self._entries_dir = project_root / ENTRIES_DIR
        self._absorb_log_path = project_root / ABSORB_LOG
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
            [self._ingestors[source]] if source and source in self._ingestors
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
        """Mark entries as absorbed into specific articles."""
        log = self._load_absorb_log()
        timestamp = datetime.now(timezone.utc).isoformat()
        for eid in entry_ids:
            log[eid] = {"absorbed_into": article_ids, "absorbed_at": timestamp}
        self._save_absorb_log(log)

    # -- Internal helpers -----------------------------------------------------

    def _deduplicate(self, entries: list[RawEntry]) -> list[RawEntry]:
        existing_ids = {e.id for e in self._load_all_entries()}
        return [e for e in entries if e.id not in existing_ids]

    def _persist_entries(self, entries: list[RawEntry]) -> None:
        self._entries_dir.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            date_str = entry.timestamp.strftime("%Y-%m-%d")
            path = self._entries_dir / f"{date_str}_{entry.id}.json"
            with open(path, "w") as f:
                json.dump(entry.model_dump(mode="json"), f, indent=2, default=str)

    def _load_all_entries(self) -> list[RawEntry]:
        if not self._entries_dir.exists():
            return []
        entries = []
        for path in sorted(self._entries_dir.glob("*.json")):
            with open(path) as f:
                entries.append(RawEntry(**json.load(f)))
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
