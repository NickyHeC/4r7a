"""Tests for employee wiki foundation (Phases A–B)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from company_brain.agents.employee_wiki.employee_wiki_manager import EmployeeWikiManagerAgent
from company_brain.agents.employee_wiki.work_event_materializer import (
    WorkEventMaterializerAgent,
    record_linear_work_event,
)
from company_brain.config import resolve_employee_wiki_dir
from company_brain.members_config import MemberSpec, MembersConfig, load_members_config
from company_brain.wiki.employee_paths import member_work_log_path, quarter_slug
from company_brain.wiki.employee_publish import APPEND, read_employee_wiki_page, write_employee_wiki_page
from company_brain.wiki.employee_store import LocalEmployeeWikiStore
from company_brain.wiki.member_bootstrap import ensure_member_wiki
from company_brain.wiki.people import ensure_people_stub
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
        "members:\n  alice:\n    email: alice@company.com\n    status: active\n"
    )
    return {"company": company, "employee": employee, "config": config_dir}


def test_resolve_employee_wiki_dir_sibling(wiki_roots, monkeypatch):
    monkeypatch.delenv("COMPANY_BRAIN_EMPLOYEE_WIKI_DIR", raising=False)
    assert resolve_employee_wiki_dir() == wiki_roots["company"].parent / "employee_wiki"


def test_write_employee_wiki_page_defaults(wiki_roots):
    store = LocalEmployeeWikiStore()
    write_employee_wiki_page(
        "alice/_index.md",
        "Current work",
        "# Current work\n\nHello\n",
        member="alice",
        store=store,
    )
    doc = store.read("alice/_index.md")
    assert doc.frontmatter["member"] == "alice"
    assert doc.frontmatter["sync"] == "private"
    assert doc.frontmatter["artifact_refs"] == []


def test_quarter_slug():
    assert quarter_slug(date(2026, 6, 15)) == "2026-Q2"
    assert member_work_log_path("alice", when=date(2026, 1, 5)) == "alice/work-log/2026-Q1.md"


def test_ensure_people_stub(wiki_roots):
    company = LocalWikiStore(root=wiki_roots["company"])
    rel = ensure_people_stub("alice", email="alice@company.com", store=company, sync_notion=False)
    assert rel == "people/alice.md"
    body = company.read(rel).body
    assert "employee_wiki/alice" in body


def test_ensure_member_wiki(wiki_roots):
    company = LocalWikiStore(root=wiki_roots["company"])
    paths = ensure_member_wiki("alice", email="alice@company.com", company_store=company, sync_notion=False)
    assert company.exists(paths["people"])
    emp = LocalEmployeeWikiStore()
    assert emp.exists(paths["index"])
    assert "Open projects" in emp.read(paths["index"]).body


def test_work_event_ledger_idempotent(wiki_roots):
    store = WorkEventStore(config_dir=wiki_roots["config"])
    e1 = record_linear_work_event(
        primary_member="alice",
        issue_id="l1",
        identifier="ENG-1",
        title="Task one",
        status="Done",
        store=store,
    )
    e2 = record_linear_work_event(
        primary_member="alice",
        issue_id="l1",
        identifier="ENG-1",
        title="Task one",
        status="Done",
        store=store,
    )
    assert e1.event_id == e2.event_id
    assert len(store.list_all()) == 1


def test_linear_materializer_appends_work_log(wiki_roots, monkeypatch):
    from unittest.mock import MagicMock

    config = MagicMock()
    store = WorkEventStore(config_dir=wiki_roots["config"])
    event = record_linear_work_event(
        primary_member="alice",
        issue_id="l2",
        identifier="ENG-2",
        title="Ship feature",
        status="Done",
        url="https://linear/ENG-2",
        store=store,
    )
    agent = WorkEventMaterializerAgent(config)
    monkeypatch.setattr(agent, "_members", load_members_config(wiki_roots["config"]))
    result = agent.run(event=event)
    assert result["status"] == "ok"
    body = read_employee_wiki_page(result["paths"][0])
    assert "ENG-2" in body
    assert "Ship feature" in body
    updated = store.get(event.event_id)
    assert "alice" in (updated.materialized.get("employee") or [])


def test_manager_dispatches_pending(wiki_roots, monkeypatch):
    from unittest.mock import MagicMock

    store = WorkEventStore(config_dir=wiki_roots["config"])
    record_linear_work_event(
        primary_member="alice",
        issue_id="l3",
        identifier="ENG-3",
        title="Another",
        status="In Progress",
        store=store,
    )
    config = MagicMock()
    agent = EmployeeWikiManagerAgent(config)
    monkeypatch.setattr(agent, "_events", store)

    def fake_run(cls, cfg, **kwargs):
        mat = WorkEventMaterializerAgent(cfg)
        monkeypatch.setattr(mat, "_members", load_members_config(wiki_roots["config"]))
        return mat.run(**kwargs)

    runtime = MagicMock()
    runtime.run.side_effect = fake_run
    monkeypatch.setattr(
        "company_brain.agents.employee_wiki.employee_wiki_manager.get_runtime",
        lambda: runtime,
    )

    result = agent.run_once()
    assert result["dispatched"] == 1


def test_load_members_config(wiki_roots):
    cfg = load_members_config(wiki_roots["config"])
    assert "alice" in cfg.members
    assert cfg.members["alice"].email == "alice@company.com"
