"""Tests for verify rollup, session_id ambient, and admin monthly LLM ops."""

from __future__ import annotations

from pathlib import Path

import pytest

from company_brain.agents.admin.admin_maintain import AdminMaintainAgent
from company_brain.agents.admin.admin_manager import AdminManager
from company_brain.agents.admin.llm_expense_report import LlmExpenseReportAgent
from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.config import AppConfig, NotionConfig, WikiConfig
from company_brain.llm.budget import record_usage, record_verify_verdict, usage_for_month
from company_brain.llm.duration import record_execute_duration
from company_brain.llm.run_context import get_run_context
from company_brain.wiki.store import LocalWikiStore


@pytest.fixture
def models_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("company_brain.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("company_brain.agents.gates.CONFIG_DIR", tmp_path)
    return tmp_path


def _cfg() -> AppConfig:
    return AppConfig(wiki=WikiConfig(), notion=NotionConfig())


def test_record_verify_verdict(models_dir, monkeypatch):
    store = StateStore()
    monkeypatch.setattr("company_brain.llm.budget.StateStore", lambda: store)

    record_verify_verdict("tiny", "ok", store=store)
    record_verify_verdict("tiny", "rework", store=store)
    record_verify_verdict("tiny", "noise", store=store)

    from company_brain.llm.budget import _month_key

    usage = usage_for_month(_month_key(), store=store)
    assert usage["agents"]["tiny"]["verify"] == {"ok": 1, "rework": 1, "noise": 1}


def test_execute_records_verify_and_session_id(models_dir, monkeypatch):
    store = StateStore()
    monkeypatch.setattr("company_brain.llm.budget.StateStore", lambda: store)
    monkeypatch.setattr("company_brain.llm.duration.StateStore", lambda: store)
    monkeypatch.setattr("company_brain.llm.budget.maybe_alert_budget", lambda **_: False)

    seen: dict[str, str | None] = {}

    class Tiny(BaseAgent):
        name = "session_specialist"

        def run(self, **kwargs):
            ctx = get_run_context()
            seen["session_id"] = ctx.session_id if ctx else None
            record_usage(
                agent=self.name,
                model="claude-sonnet-4-6",
                input_tokens=10,
                output_tokens=5,
            )
            return {"ok": True}

    Tiny(_cfg()).execute(session_id="thread-abc")
    assert seen["session_id"] == "thread-abc"

    from company_brain.llm.budget import _month_key

    usage = usage_for_month(_month_key(), store=store)
    assert usage["agents"]["session_specialist"]["verify"]["ok"] == 1
    assert usage["agents"]["session_specialist"]["last_session_id"] == "thread-abc"


def test_llm_expense_and_maintain(models_dir, tmp_path, monkeypatch):
    store = StateStore()
    wiki = LocalWikiStore(root=tmp_path / "wiki")
    monkeypatch.setattr("company_brain.llm.budget.StateStore", lambda: store)
    monkeypatch.setattr("company_brain.llm.duration.StateStore", lambda: store)
    monkeypatch.setattr("company_brain.llm.budget.maybe_alert_budget", lambda **_: False)
    monkeypatch.setattr(
        "company_brain.agents.admin.llm_expense_report.write_wiki_page",
        lambda *a, **k: _capture_write(wiki, *a, **k),
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.admin_maintain.write_wiki_page",
        lambda *a, **k: _capture_write(wiki, *a, **k),
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.admin_maintain.wiki_admin_notifier",
        lambda: _FakeNotifier(),
    )

    record_usage(
        agent="linear_stale_audit",
        model="claude-sonnet-4-6",
        input_tokens=1000,
        output_tokens=100,
    )
    for _ in range(5):
        record_execute_duration("linear_stale_audit", 120_000.0, store=store)
    record_verify_verdict("linear_stale_audit", "ok", store=store)

    cfg = _cfg()
    exp = LlmExpenseReportAgent(cfg, store=store).run(month="2026-06", sync=False)
    assert exp["path"] == "admin/llm-expense/2026-06.md"
    assert wiki.exists("admin/llm-expense/2026-06.md")

    mnt = AdminMaintainAgent(cfg, store=store).run(month="2026-06", sync=False)
    assert mnt["path"] == "admin/maintain/2026-06.md"
    assert wiki.exists("admin/agent-runtime.md")
    assert wiki.exists("admin/maintain/2026-06.md")


def test_admin_manager_dispatches_pair(models_dir, tmp_path, monkeypatch):
    store = StateStore()
    wiki = LocalWikiStore(root=tmp_path / "wiki")
    monkeypatch.setattr("company_brain.llm.budget.StateStore", lambda: store)
    monkeypatch.setattr("company_brain.llm.duration.StateStore", lambda: store)
    monkeypatch.setattr("company_brain.llm.budget.maybe_alert_budget", lambda **_: False)
    monkeypatch.setattr(
        "company_brain.agents.admin.llm_expense_report.write_wiki_page",
        lambda *a, **k: _capture_write(wiki, *a, **k),
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.admin_maintain.write_wiki_page",
        lambda *a, **k: _capture_write(wiki, *a, **k),
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.admin_maintain.wiki_admin_notifier",
        lambda: _FakeNotifier(),
    )

    import company_brain.runtime as runtime_mod
    from company_brain.runtime import LocalRuntime

    monkeypatch.setattr(runtime_mod, "get_runtime", lambda: LocalRuntime())

    result = AdminManager(_cfg()).run_once(month="2026-06", sync=False)
    assert result["month"] == "2026-06"
    assert result["expense"]["path"].endswith("2026-06.md")
    assert result["maintain"]["path"].endswith("2026-06.md")


def _capture_write(store: LocalWikiStore, rel_path: str, title: str, body: str, **kwargs):
    from company_brain.wiki.store import MarkdownDoc

    store.write(
        rel_path,
        MarkdownDoc(frontmatter={"title": title}, body=body),
    )
    return None


class _FakeNotifier:
    def emit(self, signal):
        return signal.severity in {"actionable", "alert"} and not signal.silent
