"""Tests for ambient run context, usage dimensions, and specialist duration."""

from __future__ import annotations

from pathlib import Path

import pytest

from company_brain.agents.base import SKIPPED, BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.config import AppConfig, NotionConfig, WikiConfig
from company_brain.llm.budget import (
    current_usage,
    estimate_usd,
    model_rate_known,
    record_usage,
)
from company_brain.llm.duration import (
    record_execute_duration,
    resolve_estimated_minutes,
)
from company_brain.llm.run_context import ambient_scope, get_run_context, new_run_id
from company_brain.llm.tracking import _dims_from_usage


@pytest.fixture
def models_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("company_brain.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("company_brain.agents.gates.CONFIG_DIR", tmp_path)
    return tmp_path


def _cfg() -> AppConfig:
    return AppConfig(wiki=WikiConfig(), notion=NotionConfig())



def test_ambient_scope_sets_context():
    assert get_run_context() is None
    with ambient_scope(manager="linear_manager", run_id="abc123", reason="stale_audit"):
        ctx = get_run_context()
        assert ctx is not None
        assert ctx.manager == "linear_manager"
        assert ctx.run_id == "abc123"
        assert ctx.reason == "stale_audit"
    assert get_run_context() is None


def test_record_usage_inherits_ambient_manager(models_dir, monkeypatch):
    store = StateStore()
    monkeypatch.setattr("company_brain.llm.budget.StateStore", lambda: store)
    monkeypatch.setattr("company_brain.llm.budget.maybe_alert_budget", lambda **_: False)

    with ambient_scope(manager="linear_manager", run_id=new_run_id()):
        delta = record_usage(
            agent="linear_stale_audit",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=100,
            cache_read_tokens=200,
            reasoning_tokens=50,
        )

    assert delta["cache_read_tokens"] == 200
    assert delta["reasoning_tokens"] == 50
    assert delta["manager"] == "linear_manager"
    assert delta["estimated_usd"] is not None

    usage = current_usage(store=store)
    assert usage["cache_read_tokens"] == 200
    assert usage["reasoning_tokens"] == 50
    agent = usage["agents"]["linear_stale_audit"]
    assert agent["managers"]["linear_manager"]["input_tokens"] == 1000


def test_unknown_model_leaves_usd_unset(models_dir, monkeypatch):
    store = StateStore()
    monkeypatch.setattr("company_brain.llm.budget.StateStore", lambda: store)
    monkeypatch.setattr("company_brain.llm.budget.maybe_alert_budget", lambda **_: False)

    assert not model_rate_known("totally-fake-model-xyz")
    assert estimate_usd("totally-fake-model-xyz", 1000, 100) is None

    delta = record_usage(
        agent="absorb",
        model="totally-fake-model-xyz",
        input_tokens=1000,
        output_tokens=100,
    )
    assert delta["unknown_model"] is True
    assert delta["estimated_usd"] is None
    usage = current_usage(store=store)
    assert usage["input_tokens"] == 1000
    assert usage["estimated_usd"] == 0
    assert usage["unknown_model_calls"] == 1


def test_dims_from_claude_shaped_usage():
    dims = _dims_from_usage(
        {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 3,
            "cache_creation_input_tokens": 2,
            "reasoning_tokens": 7,
        }
    )
    assert dims == {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_read_tokens": 3,
        "cache_write_tokens": 2,
        "reasoning_tokens": 7,
    }


def test_resolve_estimated_minutes_uses_p95_after_samples(models_dir, monkeypatch):
    store = StateStore()
    monkeypatch.setattr("company_brain.llm.duration.StateStore", lambda: store)

    assert resolve_estimated_minutes("linear_stale_audit", 15, store=store) == 15

    # Five samples of ~2 minutes (120_000 ms) → p95 ceil minutes = 2
    for _ in range(5):
        record_execute_duration("linear_stale_audit", 120_000.0, store=store)

    assert resolve_estimated_minutes("linear_stale_audit", 15, store=store) == 2


def test_base_agent_records_duration(models_dir, monkeypatch):
    store = StateStore()
    monkeypatch.setattr("company_brain.llm.duration.StateStore", lambda: store)

    class Tiny(BaseAgent):
        name = "tiny_specialist"

        def run(self, **kwargs):
            return {"ok": True}

    agent = Tiny(_cfg())
    assert agent.execute() == {"ok": True}
    from company_brain.llm.duration import duration_stats

    stats = duration_stats("tiny_specialist", store=store)
    assert stats["count"] == 1
    assert stats["last_ms"] >= 0


def test_manager_skips_duration_tracking(models_dir, monkeypatch):
    store = StateStore()
    monkeypatch.setattr("company_brain.llm.duration.StateStore", lambda: store)

    class Mgr(BaseAgent):
        name = "tiny_manager"
        track_duration = False

        def run(self, **kwargs):
            return {"ok": True}

    Mgr(_cfg()).execute()
    from company_brain.llm.duration import duration_stats

    assert duration_stats("tiny_manager", store=store)["count"] == 0


def test_cost_gate_skip_does_not_record_duration(models_dir, monkeypatch):
    store = StateStore()
    monkeypatch.setattr("company_brain.llm.duration.StateStore", lambda: store)

    class Skipper(BaseAgent):
        name = "skip_specialist"

        def should_run(self, **kwargs):
            return False

        def run(self, **kwargs):
            return {"ok": True}

    assert Skipper(_cfg()).execute() is SKIPPED
    from company_brain.llm.duration import duration_stats

    assert duration_stats("skip_specialist", store=store)["count"] == 0
