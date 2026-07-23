"""Who Knows — weekly rebuild of the derived expertise index.

SDK: Neither (deterministic scan of people / Slack routing / Granola).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.config import AppConfig
from company_brain.wiki.who_knows import rebuild_who_knows_index


class WhoKnowsAgent(BaseAgent):
    """Rebuild ``people/_who-knows`` index (Connect channels excluded)."""

    name = "who_knows"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)

    def should_run(self, **kwargs: Any) -> bool:
        return True

    def run(self, **kwargs: Any) -> dict[str, Any]:
        return rebuild_who_knows_index(sync=False)
