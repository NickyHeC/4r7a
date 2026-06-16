"""Ramp Card Spend Agent — categorize Ramp spend by QuickBooks category.

Reads Ramp transactions within a specified time frame through the Ramp MCP
server and categorizes spend according to each transaction's QuickBooks
accounting categories.

SDK: Anthropic Claude Agent SDK. Ramp is exposed via MCP, and this agent's job
is to connect to that data source, page through transactions, and produce a
structured categorized breakdown — a good fit for the Claude Agent SDK's MCP
support and large context window.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.config import AppConfig

from . import ramp_client

logger = logging.getLogger(__name__)

AGENT_KEY = "ramp_card_spend"

_RESULT_START = "<<<RAMP_JSON>>>"
_RESULT_END = "<<<END_RAMP_JSON>>>"


class RampCardSpendAgent(BaseAgent):
    """Categorize Ramp card spend by QuickBooks category for a date range."""

    name = "finance_ramp_card_spend"

    def __init__(self, config: AppConfig, model: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.model = model

    def run(self, *, start: str, end: str, **kwargs: Any) -> dict[str, Any]:
        """Return normalised Ramp transactions and a QuickBooks-category breakdown."""
        self.logger.info("Reading Ramp spend %s -> %s via MCP", start, end)
        try:
            raw = asyncio.run(self._query_ramp(start, end))
        except ImportError as e:
            raise RuntimeError(
                "claude-agent-sdk not installed. Add it to dependencies: "
                "pip install claude-agent-sdk"
            ) from e

        data = self._parse_result(raw)
        txns = data.get("transactions", [])
        self.logger.info("Ramp returned %d transactions", len(txns))
        return {
            "start": start,
            "end": end,
            "transactions": txns,
            "by_qb_category": data.get("by_qb_category", {}),
            "total_spend": data.get("total_spend", 0.0),
        }

    async def _query_ramp(self, start: str, end: str) -> str:
        from claude_agent_sdk import ClaudeAgentOptions, query

        prompt = self._build_prompt(start, end)
        options = ClaudeAgentOptions(
            allowed_tools=ramp_client.ramp_allowed_tools(),
            mcp_servers=ramp_client.ramp_mcp_servers(),
            **({"model": self.model} if self.model else {}),
        )

        collected: list[str] = []
        async for message in query(prompt=prompt, options=options):
            result = getattr(message, "result", None)
            if isinstance(result, str):
                collected.append(result)
            else:
                content = getattr(message, "content", None)
                if isinstance(content, str):
                    collected.append(content)
        return "\n".join(collected)

    @staticmethod
    def _build_prompt(start: str, end: str) -> str:
        return f"""Use the Ramp MCP tools to fetch ALL Ramp card transactions
settled between {start} and {end} (inclusive). Page through results fully.

For each transaction, capture:
- merchant name
- amount (as a negative number, since card spend is an outflow)
- transaction date (YYYY-MM-DD)
- the QuickBooks accounting categories assigned to it (if any)
- the Ramp merchant category (sk_category) as a fallback

Then categorize total spend by QuickBooks category.

Output ONLY a JSON object wrapped exactly between {_RESULT_START} and
{_RESULT_END}, with this shape:

{_RESULT_START}
{{
  "transactions": [
    {{"name": "...", "amount": -12.34, "date": "YYYY-MM-DD",
      "source": "Ramp", "qb_categories": ["..."], "sk_category": "..."}}
  ],
  "by_qb_category": {{"<QuickBooks category>": 123.45}},
  "total_spend": 123.45
}}
{_RESULT_END}

Do not include any commentary outside the markers."""

    @staticmethod
    def _parse_result(raw: str) -> dict[str, Any]:
        if not raw:
            return {}
        start_idx = raw.rfind(_RESULT_START)
        end_idx = raw.rfind(_RESULT_END)
        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
            logger.warning("Ramp agent output missing JSON markers")
            return {}
        blob = raw[start_idx + len(_RESULT_START):end_idx].strip()
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            logger.warning("Could not parse Ramp agent JSON output")
            return {}
