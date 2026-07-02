"""Tests for LLM tier resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from company_brain.config import save_models_config
from company_brain.llm.setup import BALANCED, PERFORMANCE, apply_mode
from company_brain.llm.tiers import (
    agent_tier,
    resolve_agent_model,
    set_tier_override,
)


@pytest.fixture
def models_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("company_brain.config.CONFIG_DIR", tmp_path)
    return tmp_path


def test_balanced_mode_agent_tiers(models_dir):
    apply_mode(BALANCED, config_dir=models_dir)
    assert agent_tier("absorb") == "reasoning"
    assert agent_tier("draft_reply") == "standard"
    assert resolve_agent_model("budget_report").provider_key == "openai"


def test_performance_mode_all_reasoning(models_dir):
    apply_mode(PERFORMANCE, config_dir=models_dir)
    assert agent_tier("draft_reply") == "reasoning"
    assert agent_tier("card_spend") == "reasoning"


def test_tier_override_persisted(models_dir):
    apply_mode(BALANCED, config_dir=models_dir)
    cfg = set_tier_override("anthropic", "reasoning", "claude-sonnet-4-6")
    save_models_config(cfg, models_dir)
    binding = resolve_agent_model("absorb", cfg)
    assert binding.model_id == "claude-sonnet-4-6"


def test_fallback_chain_default(models_dir):
    from company_brain.llm.tiers import fallback_chain

    apply_mode(BALANCED, config_dir=models_dir)
    chain = fallback_chain("anthropic", "standard")
    assert chain[0] == "claude-sonnet-4-6"
