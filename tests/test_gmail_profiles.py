"""Tests for Gmail service profiles (Phase 5)."""

import pytest

from company_brain.agents.operations.shared.profiles import (
    agent_enabled,
    normalize_domain_tags,
    profile_spec,
    resolve_profile_name,
)


@pytest.fixture(autouse=True)
def _clear_profile_env(monkeypatch):
    monkeypatch.delenv("GMAIL_PROFILE", raising=False)


def test_default_profile_is_executive_assistant(monkeypatch):
    monkeypatch.setenv("GMAIL_MAILBOX", "me")
    assert resolve_profile_name() == "executive_assistant"
    spec = profile_spec()
    assert spec.all_agents
    assert spec.investor
    assert spec.warm_intro
    assert agent_enabled("investor_tracker")
    assert agent_enabled("inbound_crm")


def test_employee_profile_flat_cold_and_newsletters(monkeypatch):
    monkeypatch.setenv("GMAIL_PROFILE", "employee")
    spec = profile_spec()
    assert not spec.investor
    assert not spec.warm_intro
    assert not spec.cold_inbound_nested
    assert not spec.newsletters_nested
    assert "Cold Inbound" in spec.domain
    assert "Newsletters" in spec.domain
    assert not agent_enabled("investor_tracker")
    assert not agent_enabled("inbound_crm")
    assert not agent_enabled("receipt_router")
    assert agent_enabled("customer_support")
    assert agent_enabled("decision_propagate")


def test_service_account_attention_one_through_three(monkeypatch):
    monkeypatch.setenv("GMAIL_PROFILE", "service_account")
    spec = profile_spec()
    assert spec.attention == ["1. Action", "2. Reply", "3. FYI"]
    assert "4. Team On It" not in spec.attention
    assert not agent_enabled("team_on_it")
    assert agent_enabled("vendor_tracker")


def test_employee_normalizes_nested_tags(monkeypatch):
    monkeypatch.setenv("GMAIL_PROFILE", "employee")
    tags = normalize_domain_tags(
        ["Cold Inbound/Sales Outreach", "Newsletters/Substack", "Investor"],
        mailbox="me",
    )
    assert tags == ["Cold Inbound", "Newsletters"]


def test_gmail_manager_always_enabled(monkeypatch):
    monkeypatch.setenv("GMAIL_PROFILE", "service_account")
    # gmail_manager is started by onboarding regardless; not in specialist list
    assert agent_enabled("inbox_triage")
    assert agent_enabled("thread_watcher")
