"""LLM vibe evals: run agents against fixtures and post spot checks to Slack.

Ramp's "vibe eval" loop — periodic human grading of LLM output quality. Fixtures
live under ``tests/fixtures/llm/<agent>/``; each run posts input summary, output,
and rubric to the configured wiki ops channel (default ``#wiki``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from company_brain.config import load_config, load_models_config
from company_brain.llm.admin_notify import wiki_eval_notifier
from company_brain.notify import ACTIONABLE, Signal

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "llm"

# Agents with offline fixture runners (no live Gmail/Mercury/Ramp).
DEFAULT_AGENTS = ("budget_report", "draft_reply", "absorb")


@dataclass
class SpotCheckResult:
    agent: str
    fixture_dir: Path
    output: str
    rubric: str
    error: str | None = None


def spot_check_config() -> dict[str, Any]:
    cfg = load_models_config()
    spec = getattr(cfg, "eval_spotcheck", None)
    if spec is None:
        return {"enabled": True, "channel": "#wiki", "agents": list(DEFAULT_AGENTS)}
    return {
        "enabled": getattr(spec, "enabled", True),
        "channel": getattr(spec, "channel", None) or "#wiki",
        "agents": list(getattr(spec, "agents", None) or DEFAULT_AGENTS),
    }


def fixture_dir_for(agent: str) -> Path:
    return FIXTURES_ROOT / agent


def load_rubric(agent_dir: Path) -> str:
    path = agent_dir / "rubric.md"
    if not path.exists():
        return "Review output for accuracy, tone, and completeness."
    return path.read_text(encoding="utf-8").strip()


def _read(agent_dir: Path, name: str) -> str:
    path = agent_dir / name
    if not path.exists():
        raise FileNotFoundError(f"Missing fixture {path}")
    return path.read_text(encoding="utf-8").strip()


def _run_budget_report(agent_dir: Path) -> str:
    from company_brain.agents.finance.budget_report import BudgetReportAgent

    metric = _read(agent_dir, "metric.md")
    timeline = _read(agent_dir, "timeline.md")
    agent = BudgetReportAgent(load_config())
    return agent._compose_section("Q1 2026", metric, timeline)


def _run_draft_reply(agent_dir: Path) -> str:
    thread = _read(agent_dir, "thread.txt")
    prompt = f"""You are drafting a reply for the CEO's Gmail inbox.

THREAD (fixture — no Gmail access):
{thread}

Compose a concise, professional reply: direct, warm, no fluff.
Output only the draft body text."""

    async def _call() -> str:
        from claude_agent_sdk import ClaudeAgentOptions

        from company_brain.llm import claude as llm_claude
        from company_brain.llm.tracking import iter_claude_query

        options = ClaudeAgentOptions(
            env=llm_claude.options_env(),
            **llm_claude.model_kwargs(agent_name="draft_reply"),
        )
        out: list[str] = []
        async for message in iter_claude_query("draft_reply", prompt=prompt, options=options):
            result = getattr(message, "result", None)
            if isinstance(result, str):
                out.append(result)
        return "\n".join(out).strip()

    return asyncio.run(_call())


def _run_absorb(agent_dir: Path) -> str:
    entries = _read(agent_dir, "entries.md")
    prompt = f"""You are spot-checking the absorb writer. Given these raw entries,
write ONE focused wiki paragraph (theme-organized, Wikipedia tone, no em dashes).
Do not create files — output only the paragraph.

RAW ENTRIES:
{entries}"""

    async def _call() -> str:
        from claude_agent_sdk import ClaudeAgentOptions

        from company_brain.llm import claude as llm_claude
        from company_brain.llm.tracking import iter_claude_query

        options = ClaudeAgentOptions(
            env=llm_claude.options_env(),
            **llm_claude.model_kwargs(agent_name="absorb"),
        )
        out: list[str] = []
        async for message in iter_claude_query("absorb", prompt=prompt, options=options):
            result = getattr(message, "result", None)
            if isinstance(result, str):
                out.append(result)
        return "\n".join(out).strip()

    return asyncio.run(_call())


_RUNNERS: dict[str, Callable[[Path], str]] = {
    "budget_report": _run_budget_report,
    "draft_reply": _run_draft_reply,
    "absorb": _run_absorb,
}


def run_spot_check(agent: str, *, fixture_root: Path | None = None) -> SpotCheckResult:
    """Run one agent against its fixture directory."""
    from company_brain.llm.run_budget import run_budget_scope

    root = fixture_root or fixture_dir_for(agent)
    rubric = load_rubric(root)
    runner = _RUNNERS.get(agent)
    if runner is None:
        return SpotCheckResult(
            agent=agent,
            fixture_dir=root,
            output="",
            rubric=rubric,
            error=f"No offline runner for agent '{agent}'",
        )
    if not root.is_dir():
        return SpotCheckResult(
            agent=agent,
            fixture_dir=root,
            output="",
            rubric=rubric,
            error=f"Fixture directory missing: {root}",
        )
    try:
        with run_budget_scope(agent):
            output = runner(root)
    except Exception as exc:
        return SpotCheckResult(
            agent=agent,
            fixture_dir=root,
            output="",
            rubric=rubric,
            error=str(exc),
        )
    return SpotCheckResult(agent=agent, fixture_dir=root, output=output, rubric=rubric)


def format_slack_message(result: SpotCheckResult, *, max_output_chars: int = 2800) -> str:
    """Format a spot-check result for Slack (#wiki channel)."""
    lines = [f"*LLM spot check — `{result.agent}`*", ""]
    if result.error:
        lines.append(f"_Run failed:_ {result.error}")
        lines.append("")
    elif result.output.strip():
        body = result.output.strip()
        if len(body) > max_output_chars:
            body = body[: max_output_chars - 3] + "..."
        lines.append("*Output:*")
        lines.append("```")
        lines.append(body)
        lines.append("```")
        lines.append("")
    lines.append("*Rubric (reply in thread with 👍 / 👎 or notes):*")
    rubric = result.rubric.strip()
    if len(rubric) > 800:
        rubric = rubric[:797] + "..."
    lines.append(rubric)
    lines.append("")
    lines.append(f"_Fixture:_ `{result.fixture_dir.relative_to(PROJECT_ROOT)}`")
    return "\n".join(lines)


def run_all_spot_checks(
    agents: list[str] | None = None,
    *,
    post: bool = True,
) -> list[SpotCheckResult]:
    """Run spot checks for configured agents; optionally post each to Slack."""
    cfg = spot_check_config()
    if not cfg.get("enabled", True):
        return []
    names = agents or cfg.get("agents") or list(DEFAULT_AGENTS)
    notifier = wiki_eval_notifier(cfg.get("channel") or "#wiki")
    results: list[SpotCheckResult] = []
    for name in names:
        result = run_spot_check(name)
        results.append(result)
        if post:
            notifier.emit(
                Signal(text=format_slack_message(result), severity=ACTIONABLE),
            )
    return results
