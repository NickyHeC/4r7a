"""Tests for model health doctor (mocked pings)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from company_brain.llm.health import run_model_health
from company_brain.llm.setup import apply_mode


@pytest.fixture
def models_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("company_brain.config.CONFIG_DIR", tmp_path)
    return tmp_path


def test_health_applies_fallback(models_dir):
    apply_mode("balanced", config_dir=models_dir)

    def fake_ping(provider_key: str, model_id: str):
        if model_id == "claude-opus-4-6":
            return False, "unavailable"
        if model_id == "claude-sonnet-4-6":
            return True, "ok"
        return False, "skip"

    with patch("company_brain.llm.health.ping_model", side_effect=fake_ping):
        report = run_model_health(apply_fallbacks=True, notify=False, cfg=None)

    assert report.fallbacks_applied
    assert "claude-sonnet-4-6" in report.fallbacks_applied[0]
