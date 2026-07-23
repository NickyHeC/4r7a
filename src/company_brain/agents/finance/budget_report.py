"""Budget Report Agent (ephemeral).

Started on command by quarterly_calculation. Matches the quarter's expenses to
major company events in the wiki Company Timeline (using Quarterly Metric data)
and appends to the wiki Budget Summary before the Notion mirror.

SDK: Anthropic Claude Agent SDK. Matching spend to qualitative company events is
a reasoning task over two wiki documents — well suited to a single competent
assistant with a large context window. Falls back to a deterministic summary if
the SDK is unavailable.
"""

from __future__ import annotations

import asyncio
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore, changed_since
from company_brain.config import AppConfig

from .shared import notion_pages

BUDGET_KEY = "budget_summary"
BUDGET_TERMS = ["Budget Summary"]
TIMELINE_KEY = "timeline"
TIMELINE_TERMS = ["Company Timeline"]
QUARTERLY_KEY = "quarterly_metric"


class BudgetReportAgent(BaseAgent):
    """Match quarterly expenses to company events and update Budget Summary.

    Append agent: each quarter's section is prepended (newest on top).
    """

    name = "finance_budget_report"
    WRITE_MODE = "append"

    def __init__(self, config: AppConfig, model: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.model = model
        self._state = StateStore()

    def should_run(self, *, quarter: str, **kwargs: Any) -> bool:
        """Cost gate: rebuild only when this quarter's metric content changed."""
        return changed_since(
            f"budget_report:{quarter}",
            self._source_signature(quarter),
            store=self._state,
            update=False,
        )

    def run(self, *, quarter: str, **kwargs: Any) -> dict[str, Any]:
        heading = f"{quarter[-2:]} {quarter[:4]}"
        self.logger.info("Building budget report for %s", heading)

        metric_path = notion_pages.get_page_handle(QUARTERLY_KEY)
        metric_text = notion_pages.read_page(metric_path) if metric_path else ""

        timeline_path = notion_pages.ensure_page(
            TIMELINE_KEY,
            TIMELINE_TERMS,
            "Company Timeline",
        )
        timeline_text = notion_pages.read_page(timeline_path)

        section = self._compose_section(heading, metric_text, timeline_text)

        budget_path = notion_pages.ensure_page(BUDGET_KEY, BUDGET_TERMS, "Budget Summary")
        notion_pages.prepend_page_body(budget_path, section)
        self._state.set(f"budget_report:{quarter}", self._source_signature(quarter))

        return {"quarter": quarter, "wiki_path": budget_path, "section": section}

    @staticmethod
    def _source_signature(quarter: str) -> str:
        import hashlib

        metric = notion_pages.read_page(notion_pages.wiki_path(QUARTERLY_KEY))
        timeline = notion_pages.read_page(notion_pages.wiki_path(TIMELINE_KEY))
        return hashlib.sha256(f"{quarter}:{metric}:{timeline}".encode()).hexdigest()[:16]

    def _compose_section(self, heading: str, metric_text: str, timeline_text: str) -> str:
        from company_brain.llm.tiers import resolve_agent_model

        provider_key = resolve_agent_model("budget_report").provider_key
        try:
            if provider_key == "openai":
                body = asyncio.run(
                    self._compose_with_openai(heading, metric_text, timeline_text),
                )
            else:
                body = asyncio.run(
                    self._compose_with_claude(heading, metric_text, timeline_text),
                )
            if body.strip():
                return body
        except ImportError:
            self.logger.warning("LLM SDK not installed — using deterministic budget summary")
        except Exception:
            self.logger.exception("Budget composition failed — using deterministic fallback")
        return self._deterministic_section(heading, metric_text)

    @staticmethod
    def _budget_prompt(heading: str, metric_text: str, timeline_text: str) -> str:
        return f"""You are a finance analyst. Write a Budget Summary section for
**{heading}**. Match the quarter's expenses to major company events.

QUARTERLY METRIC DATA:
{metric_text or "(none available)"}

COMPANY TIMELINE (major events):
{timeline_text or "(none available)"}

Write a concise markdown section that:
- starts with the heading: ## {heading}
- summarizes spend drivers and ties notable spend to timeline events
- calls out anything anomalous
Output only the markdown section."""

    async def _compose_with_openai(
        self,
        heading: str,
        metric_text: str,
        timeline_text: str,
    ) -> str:
        from agents import Agent

        from company_brain.llm import openai_agents as oa
        from company_brain.llm.tracking import run_openai_sync

        prompt = self._budget_prompt(heading, metric_text, timeline_text)
        agent = Agent(
            name="budget_report",
            instructions="You write concise finance budget summary sections.",
            model=oa.make_model(agent_name="budget_report"),
        )
        result = run_openai_sync(
            "budget_report",
            agent,
            prompt,
            run_config=oa.make_run_config(agent_name="budget_report"),
        )
        return str(result.final_output or "")

    async def _compose_with_claude(self, heading: str, metric_text: str, timeline_text: str) -> str:
        from claude_agent_sdk import ClaudeAgentOptions

        prompt = self._budget_prompt(heading, metric_text, timeline_text)

        from company_brain.llm import claude as llm_claude
        from company_brain.llm.tracking import iter_claude_query

        options = ClaudeAgentOptions(
            env=llm_claude.options_env(),
            **llm_claude.model_kwargs(self.model, agent_name="budget_report"),
        )
        out: list[str] = []
        async for message in iter_claude_query("budget_report", prompt=prompt, options=options):
            result = getattr(message, "result", None)
            if isinstance(result, str):
                out.append(result)
        return "\n".join(out)

    @staticmethod
    def _deterministic_section(heading: str, metric_text: str) -> str:
        lines = [f"## {heading}", ""]
        lines.append(
            "Budget summary generated from quarterly metrics "
            "(event matching unavailable without the Claude Agent SDK)."
        )
        lines.append("")
        if metric_text:
            lines.append("Source quarterly metrics:")
            lines.append("")
            lines.append(metric_text.strip()[:2000])
        lines.append("")
        return "\n".join(lines)
