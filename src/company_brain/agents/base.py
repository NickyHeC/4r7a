"""Base agent class: lifecycle, logging, and config for all agents."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from company_brain.config import AppConfig

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base class for company-brain agents.

    Agents are long-lived processes or triggered tasks that perform specific
    wiki maintenance operations (ingestion, cleanup, sync, etc.).
    """

    name: str = "base-agent"

    def __init__(self, config: AppConfig, **kwargs: Any):
        self.config = config
        self.logger = logging.getLogger(f"company_brain.agents.{self.name}")

    @abstractmethod
    def run(self, **kwargs: Any) -> Any:
        """Execute the agent's primary task."""
        ...

    def setup(self) -> None:
        """Optional setup hook, called before run()."""
        pass

    def teardown(self) -> None:
        """Optional teardown hook, called after run()."""
        pass

    def execute(self, **kwargs: Any) -> Any:
        """Full agent lifecycle: setup -> run -> teardown."""
        self.logger.info("Starting agent '%s'", self.name)
        try:
            self.setup()
            result = self.run(**kwargs)
            self.logger.info("Agent '%s' completed successfully", self.name)
            return result
        except Exception:
            self.logger.exception("Agent '%s' failed", self.name)
            raise
        finally:
            self.teardown()
