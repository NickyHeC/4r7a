"""Tests for LLM vibe-eval spot checks."""

from __future__ import annotations

from company_brain.llm.spot_check import (
    FIXTURES_ROOT,
    format_slack_message,
    load_rubric,
    run_spot_check,
    spot_check_config,
)


def test_spot_check_config_defaults():
    cfg = spot_check_config()
    assert cfg["channel"] == "#wiki"
    assert "budget_report" in cfg["agents"]


def test_load_rubric():
    rubric = load_rubric(FIXTURES_ROOT / "budget_report")
    assert "March expense spike" in rubric


def test_run_spot_check_missing_runner():
    result = run_spot_check("nonexistent_agent")
    assert result.error
    assert "No offline runner" in result.error


def test_run_budget_report_deterministic_fallback(monkeypatch):
    from company_brain.agents.finance import budget_report as br

    def fake_compose(self, heading, metric_text, timeline_text):
        return f"## {heading}\n\nDeterministic stub.\n"

    monkeypatch.setattr(br.BudgetReportAgent, "_compose_section", fake_compose)
    result = run_spot_check("budget_report")
    assert result.error is None
    assert "Deterministic stub" in result.output


def test_format_slack_message_includes_rubric():
    from company_brain.llm import spot_check as sc

    stub = sc.SpotCheckResult(
        agent="budget_report",
        fixture_dir=FIXTURES_ROOT / "budget_report",
        output="Sample output line.",
        rubric="Check accuracy.",
    )
    msg = format_slack_message(stub)
    assert "*LLM spot check" in msg
    assert "Sample output line" in msg
    assert "Check accuracy" in msg
    assert "#wiki" not in msg  # channel is not in message body


def test_run_all_spot_checks_posts(monkeypatch):
    from company_brain.llm import spot_check as sc

    posted: list[str] = []

    class FakeNotifier:
        def emit(self, signal):
            posted.append(signal.text)
            return True

    monkeypatch.setattr(sc, "wiki_eval_notifier", lambda channel=None: FakeNotifier())
    monkeypatch.setattr(
        sc,
        "run_spot_check",
        lambda agent, fixture_root=None: sc.SpotCheckResult(
            agent=agent,
            fixture_dir=FIXTURES_ROOT / agent,
            output="ok",
            rubric="r",
        ),
    )
    results = sc.run_all_spot_checks(agents=["budget_report"], post=True)
    assert len(results) == 1
    assert len(posted) == 1
