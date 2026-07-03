"""Tests for LLM budget tracking and limit resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from company_brain.agents.gates import StateStore
from company_brain.config import ModelsConfig, RunLimitValues, save_models_config
from company_brain.llm.budget import (
    SPEND_BUILDER,
    SPEND_RUNTIME,
    budget_status,
    estimate_usd,
    record_usage,
    resolve_run_limits,
    resolve_spend_category,
)
from company_brain.llm.tracking import record_from_openai_result


@pytest.fixture
def models_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("company_brain.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("company_brain.agents.gates.CONFIG_DIR", tmp_path)
    return tmp_path


def test_resolve_spend_category_defaults(models_dir):
    assert resolve_spend_category("absorb") == SPEND_RUNTIME
    assert resolve_spend_category("builder") == SPEND_BUILDER


def test_resolve_run_limits_merges_tier_and_agent(models_dir):
    limits = resolve_run_limits("absorb")
    assert limits.max_usd_per_run == 8.0
    assert limits.max_steps_per_run == 50


def test_resolve_run_limits_builder_profile(models_dir):
    limits = resolve_run_limits("builder")
    assert limits.max_usd_per_run == 10.0
    assert limits.max_steps_per_run == 80


def test_estimate_usd_uses_model_rates(models_dir):
    cost = estimate_usd("claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert cost == pytest.approx(18.0)


def test_record_usage_accumulates_by_category(models_dir, monkeypatch):
    store = StateStore()
    monkeypatch.setattr("company_brain.llm.budget.StateStore", lambda: store)
    monkeypatch.setattr("company_brain.llm.budget.maybe_alert_budget", lambda **_: False)

    record_usage(
        agent="absorb",
        model="claude-sonnet-4-6",
        input_tokens=1000,
        output_tokens=500,
    )
    record_usage(
        agent="builder",
        model="claude-sonnet-4-6",
        input_tokens=2000,
        output_tokens=1000,
        spend_category=SPEND_BUILDER,
    )

    status = budget_status(store=store)
    assert status["input_tokens"] == 3000
    assert status["runtime_usd"] > 0
    assert status["builder_usd"] > 0
    assert status["spent_usd"] == pytest.approx(status["runtime_usd"] + status["builder_usd"])


def test_record_from_openai_result(models_dir, monkeypatch):
    store = StateStore()
    monkeypatch.setattr("company_brain.llm.budget.StateStore", lambda: store)
    monkeypatch.setattr("company_brain.llm.budget.maybe_alert_budget", lambda **_: False)

    class Usage:
        input_tokens = 1200
        output_tokens = 300

    class Wrapper:
        usage = Usage()

    class Result:
        context_wrapper = Wrapper()

    record_from_openai_result("budget_report", Result(), model="gpt-5.5")
    usage = budget_status(store=store)
    assert usage["input_tokens"] == 1200
    assert usage["output_tokens"] == 300
    assert usage["spent_usd"] > 0


def test_custom_run_limits_from_yaml(models_dir):
    cfg = ModelsConfig(
        run_limits={
            "defaults": RunLimitValues(max_usd_per_run=0.25),
            "agents": {"draft_reply": RunLimitValues(max_usd_per_run=0.99)},
        },
    )
    save_models_config(cfg, models_dir)
    limits = resolve_run_limits("draft_reply")
    assert limits.max_usd_per_run == 0.99
