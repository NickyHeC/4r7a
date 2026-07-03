"""Tests for per-run budget enforcement (Layer B)."""

from __future__ import annotations

from pathlib import Path

import pytest

from company_brain.config import ModelsConfig, RunLimitsSpec, RunLimitValues, save_models_config
from company_brain.llm.budget import record_usage, resolve_run_limits
from company_brain.llm.run_budget import (
    RunLimitExceededError,
    run_budget_scope,
    start_run_budget,
)
from company_brain.llm.tiers import resolve_llm_agent_key


@pytest.fixture
def models_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("company_brain.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("company_brain.agents.gates.CONFIG_DIR", tmp_path)
    return tmp_path


def test_resolve_llm_agent_key_maps_finance_prefix():
    assert resolve_llm_agent_key("finance_budget_report") == "budget_report"
    assert resolve_llm_agent_key("draft_reply") == "draft_reply"
    assert resolve_llm_agent_key("github_open_pr") is None


def test_resolve_run_limits_via_finance_agent_name(models_dir):
    limits = resolve_run_limits("finance_budget_report")
    assert limits.max_usd_per_run == 1.50


def test_start_run_budget_uses_agent_overrides(models_dir):
    budget = start_run_budget("finance_budget_report")
    assert budget.llm_key == "budget_report"
    assert budget.limits.max_usd_per_run == 1.50


def test_run_budget_blocks_usd_via_record_usage(models_dir, monkeypatch):
    monkeypatch.setattr("company_brain.llm.budget.maybe_alert_budget", lambda **_: False)
    save_models_config(
        ModelsConfig(
            run_limits=RunLimitsSpec(
                agents={"draft_reply": RunLimitValues(max_usd_per_run=0.01)},
            ),
        ),
        models_dir,
    )
    with run_budget_scope("draft_reply"):
        with pytest.raises(RunLimitExceededError, match="max_usd_per_run"):
            record_usage(
                agent="draft_reply",
                model="claude-sonnet-4-6",
                input_tokens=50_000,
                output_tokens=10_000,
            )


def test_run_budget_blocks_execute_steps(models_dir):
    save_models_config(
        ModelsConfig(
            run_limits=RunLimitsSpec(
                defaults=RunLimitValues(max_steps_per_run=2),
                tiers={"standard": RunLimitValues(max_steps_per_run=2)},
            ),
        ),
        models_dir,
    )
    budget = start_run_budget("github_open_pr")
    budget.begin_execute_step()
    budget.begin_execute_step()
    with pytest.raises(RunLimitExceededError, match="max_steps_per_run"):
        budget.begin_execute_step()


def test_run_budget_blocks_tool_calls():
    budget = start_run_budget("draft_reply")
    budget.limits = RunLimitValues(max_tool_calls_per_run=3)
    budget.set_tool_calls(3)
    with pytest.raises(RunLimitExceededError, match="max_tool_calls_per_run"):
        budget.add_tool_calls(1)
