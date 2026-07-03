"""Tests for LLM vendor bill reconciliation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from company_brain.agents.gates import StateStore
from company_brain.llm.budget import USAGE_PREFIX
from company_brain.llm.reconcile import (
    match_llm_vendor,
    reconciliation_report,
    sum_vendor_llm_spend,
)


@pytest.fixture
def models_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("company_brain.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("company_brain.agents.gates.CONFIG_DIR", tmp_path)
    return tmp_path


def test_match_llm_vendor():
    assert match_llm_vendor("ANTHROPIC PBC") == "anthropic"
    assert match_llm_vendor("OpenAI * ChatGPT") == "openai"
    assert match_llm_vendor("Acme Corp") is None


def test_reconciliation_report_warns_on_drift(models_dir, monkeypatch):
    monkeypatch.setattr("company_brain.llm.budget.maybe_alert_budget", lambda **_: False)
    store = StateStore()
    store.set(
        f"{USAGE_PREFIX}2026-07",
        {"estimated_usd": 10.0, "input_tokens": 100, "output_tokens": 50, "categories": {}},
    )

    fake_vendor = {"by_vendor": {"anthropic": 20.0}, "total_usd": 20.0, "sources": ["mercury"]}
    with patch("company_brain.llm.reconcile.sum_vendor_llm_spend", return_value=fake_vendor):
        report = reconciliation_report(month="2026-07", store=store, drift_warn_percent=25.0)

    assert report["tracked_usd"] == 10.0
    assert report["vendor_usd"] == 20.0
    assert report["warn"] is True


def test_reconciliation_report_passes_when_aligned(models_dir):
    store = StateStore()
    store.set(
        f"{USAGE_PREFIX}2026-07",
        {"estimated_usd": 50.0, "input_tokens": 0, "output_tokens": 0, "categories": {}},
    )
    fake_vendor = {"by_vendor": {"openai": 50.0}, "total_usd": 50.0, "sources": ["mercury"]}
    with patch("company_brain.llm.reconcile.sum_vendor_llm_spend", return_value=fake_vendor):
        report = reconciliation_report(month="2026-07", store=store)
    assert report["warn"] is False


def test_sum_vendor_llm_spend_mercury(models_dir):
    txns = [
        {"amount": -30.0, "counterparty": "Anthropic"},
        {"amount": -10.0, "counterparty": "OpenAI"},
        {"amount": -5.0, "counterparty": "Coffee Shop"},
    ]

    class FakeMc:
        @staticmethod
        def list_credit_accounts():
            return ["acct"]

        @staticmethod
        def list_all_transactions(accounts, start, end):
            return txns

        @staticmethod
        def is_internal_transfer(txn):
            return False

        @staticmethod
        def txn_counterparty(txn):
            return txn.get("counterparty", "")

    with patch("company_brain.llm.reconcile._mercury_llm_spend") as mercury:
        mercury.return_value = {"anthropic": 30.0, "openai": 10.0}
        result = sum_vendor_llm_spend(month="2026-07")
    assert result["total_usd"] == 40.0
