"""Tests for employee wiki platform materializers (Phase E)."""

from __future__ import annotations

from pathlib import Path

import pytest

from company_brain.agents.employee_wiki.work_event_materializer import (
    WorkEventMaterializerAgent,
    record_gmail_work_event,
    record_granola_work_event,
    record_slack_work_event,
)
from company_brain.members_config import load_members_config
from company_brain.wiki.employee_publish import read_employee_wiki_page
from company_brain.wiki.member_bootstrap import ensure_member_wiki
from company_brain.wiki.store import LocalWikiStore
from company_brain.wiki.work_events import WorkEventStore


@pytest.fixture
def wiki_roots(tmp_path: Path, monkeypatch):
    company = tmp_path / "wiki"
    employee = tmp_path / "employee_wiki"
    config_dir = tmp_path / "config"
    company.mkdir()
    employee.mkdir()
    config_dir.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(company))
    monkeypatch.setenv("COMPANY_BRAIN_EMPLOYEE_WIKI_DIR", str(employee))
    monkeypatch.setattr("company_brain.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("company_brain.members_config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("company_brain.wiki.work_events.CONFIG_DIR", config_dir)
    (config_dir / "members.yaml").write_text(
        "members:\n"
        "  alice:\n"
        "    email: alice@company.com\n"
        "    bindings:\n"
        "      granola_label: alice\n"
        "      gmail_mailbox: alice@company.com\n"
        "      slack_user_id: U111\n"
        "  bob:\n"
        "    email: bob@company.com\n"
        "    bindings:\n"
        "      gmail_mailbox: bob@company.com\n"
    )
    return {"company": company, "employee": employee, "config": config_dir}


def test_granola_materializes_primary_and_contributor(wiki_roots, monkeypatch):
    from unittest.mock import MagicMock

    company = LocalWikiStore(root=wiki_roots["company"])
    ensure_member_wiki("alice", company_store=company, sync_notion=False)
    ensure_member_wiki("bob", company_store=company, sync_notion=False)

    store = WorkEventStore(config_dir=wiki_roots["config"])
    event = record_granola_work_event(
        note_id="n1",
        meeting_date="2026-06-29",
        title="Sprint planning",
        member_label="alice",
        detail={"attendees": [{"email": "bob@company.com", "name": "Bob"}]},
        action_item_count=2,
        store=store,
        members=load_members_config(wiki_roots["config"]),
    )
    assert event is not None
    assert event.contributors == ["bob"]

    config = MagicMock()
    agent = WorkEventMaterializerAgent(config)
    monkeypatch.setattr(agent, "_members", load_members_config(wiki_roots["config"]))
    result = agent.run(event=event)
    assert result["status"] == "ok"
    assert set(result["materialized"]) == {"alice", "bob"}

    alice_log = read_employee_wiki_page(result["paths"][0])
    assert "Sprint planning" in alice_log
    bob_log = read_employee_wiki_page(result["paths"][1])
    assert "contributor" in bob_log


def test_gmail_materializer(wiki_roots, monkeypatch):
    from unittest.mock import MagicMock

    company = LocalWikiStore(root=wiki_roots["company"])
    ensure_member_wiki("alice", company_store=company, sync_notion=False)
    store = WorkEventStore(config_dir=wiki_roots["config"])
    event = record_gmail_work_event(
        primary_member="alice",
        message_id="msg-1",
        subject="Fix login bug",
        task_class="inbox_action",
        linear_identifier="ENG-9",
        url="https://linear/ENG-9",
        store=store,
    )
    assert event is not None

    config = MagicMock()
    agent = WorkEventMaterializerAgent(config)
    monkeypatch.setattr(agent, "_members", load_members_config(wiki_roots["config"]))
    result = agent.run(event=event)
    assert result["status"] == "ok"
    body = read_employee_wiki_page(result["paths"][0])
    assert "Fix login bug" in body
    assert "ENG-9" in body


def test_slack_idempotent_and_materializes(wiki_roots, monkeypatch):
    from unittest.mock import MagicMock

    company = LocalWikiStore(root=wiki_roots["company"])
    ensure_member_wiki("alice", company_store=company, sync_notion=False)
    store = WorkEventStore(config_dir=wiki_roots["config"])
    e1 = record_slack_work_event(
        primary_member="alice",
        channel="C1",
        thread_ts="123.456",
        title="Ship the dashboard",
        store=store,
    )
    e2 = record_slack_work_event(
        primary_member="alice",
        channel="C1",
        thread_ts="123.456",
        title="Ship the dashboard",
        store=store,
    )
    assert e1 and e2
    assert e1.event_id == e2.event_id
    assert len(store.list_all()) == 1

    config = MagicMock()
    agent = WorkEventMaterializerAgent(config)
    monkeypatch.setattr(agent, "_members", load_members_config(wiki_roots["config"]))
    result = agent.run(event=e1)
    assert result["status"] == "ok"
    assert "Ship the dashboard" in read_employee_wiki_page(result["paths"][0])


def test_index_refreshed_after_materialize(wiki_roots, monkeypatch):
    from unittest.mock import MagicMock

    company = LocalWikiStore(root=wiki_roots["company"])
    ensure_member_wiki("alice", company_store=company, sync_notion=False)
    store = WorkEventStore(config_dir=wiki_roots["config"])
    event = record_gmail_work_event(
        primary_member="alice",
        message_id="msg-2",
        subject="Quarterly review prep",
        task_class="inbox_action",
        store=store,
    )
    config = MagicMock()
    agent = WorkEventMaterializerAgent(config)
    monkeypatch.setattr(agent, "_members", load_members_config(wiki_roots["config"]))
    agent.run(event=event)

    index = read_employee_wiki_page("alice/_index.md")
    assert "Quarterly review prep" in index


def test_slack_record_skips_without_member(wiki_roots):
    store = WorkEventStore(config_dir=wiki_roots["config"])
    assert record_slack_work_event(
        primary_member="",
        channel="C1",
        thread_ts="1.0",
        title="noop",
        store=store,
    ) is None
