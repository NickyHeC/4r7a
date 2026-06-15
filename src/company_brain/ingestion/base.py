"""Base ingestion agent: abstract interface for all source connectors."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from company_brain.ingestion.entry import RawEntry

logger = logging.getLogger(__name__)


class BaseIngestor(ABC):
    """Abstract base for source connectors.

    Subclasses implement connect/fetch/transform for their specific source
    (Slack, GitHub, Confluence, etc.). The pipeline orchestrator calls these
    methods in sequence.
    """

    name: str = "base"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._connected = False

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the source. Raise on failure."""
        ...

    @abstractmethod
    def fetch(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch raw data from the source.

        Returns a list of raw data dicts that will be passed to transform().
        kwargs may include date ranges, filters, etc.
        """
        ...

    @abstractmethod
    def transform(self, raw_data: list[dict[str, Any]]) -> list[RawEntry]:
        """Convert raw source data into RawEntry objects."""
        ...

    def ingest(self, **kwargs: Any) -> list[RawEntry]:
        """Full ingest cycle: connect, fetch, transform."""
        logger.info("Starting ingestion from %s", self.name)

        if not self._connected:
            self.connect()
            self._connected = True

        raw_data = self.fetch(**kwargs)
        logger.info("Fetched %d items from %s", len(raw_data), self.name)

        entries = self.transform(raw_data)
        logger.info("Transformed into %d entries from %s", len(entries), self.name)

        return entries

    def disconnect(self) -> None:
        """Clean up resources. Override if the source needs explicit teardown."""
        self._connected = False
