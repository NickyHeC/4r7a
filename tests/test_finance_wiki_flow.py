"""Finance reports remain Markdown-first and advance gates only after success."""

from __future__ import annotations

from unittest.mock import MagicMock

from company_brain.agents.finance.budget_report import BudgetReportAgent
from company_brain.agents.finance.monthly_expense import MonthlyExpenseManager
from company_brain.agents.finance.quarterly_calculation import QuarterlyCalculationManager
from company_brain.agents.finance.request_manual_accounting import RequestManualAccountingAgent
from company_brain.agents.finance.shared import notion_pages
from company_brain.agents.finance.subscription_audit import SubscriptionAuditAgent
from company_brain.agents.gates import StateStore
from company_brain.runtime.fleet_gate import request_pause
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


def test_finance_page_adapter_writes_markdown_with_explicit_modes(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    path = notion_pages.wiki_path("quarterly_metric")

    notion_pages.update_page_body(path, "# Quarterly Metric\n\nInitial\n")
    notion_pages.prepend_page_body(path, "## Q2 2026\n\nUpdated\n")

    doc = LocalWikiStore(root=wiki).read(path)
    assert doc.frontmatter["title"] == "Quarterly Metric"
    assert doc.body.index("## Q2 2026") < doc.body.index("Initial")


def test_budget_gate_marks_only_after_report_write(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    store = LocalWikiStore(root=wiki)
    store.write(
        "finance/quarterly-metric.md",
        MarkdownDoc(body="# Quarterly Metric\n\n## Q2 2026\n\nExpenses: 10\n"),
    )
    store.write(
        "operations/decisions/timeline.md",
        MarkdownDoc(body="# Company Timeline\n\n- Launch\n"),
    )
    agent = BudgetReportAgent(MagicMock())
    agent._state = StateStore(path=tmp_path / "state.json")
    agent._compose_section = MagicMock(return_value="## Q2 2026\n\nSummary")  # type: ignore[method-assign]
    assert agent.should_run(quarter="2026-Q2") is True
    out = agent.run(quarter="2026-Q2")
    assert out["wiki_path"] == "finance/budget-summary.md"
    assert store.exists("finance/budget-summary.md")
    assert agent.should_run(quarter="2026-Q2") is False


def test_subscription_gate_marks_after_report_write(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(tmp_path / "wiki"))
    (tmp_path / "wiki").mkdir()
    agent = SubscriptionAuditAgent(MagicMock())
    agent._state = StateStore(path=tmp_path / "state.json")
    agent._detect_recurring = MagicMock(return_value=[])  # type: ignore[method-assign]
    agent._build_report = MagicMock(return_value="# Subscriptions\n\nNone\n")  # type: ignore[method-assign]
    agent._post_slack = MagicMock()  # type: ignore[method-assign]
    assert agent.should_run(quarter="2026-Q2") is True
    out = agent.run(quarter="2026-Q2")
    assert out["wiki_path"] == "finance/subscription.md"
    agent._detect_recurring.assert_called_once_with(["2026-04", "2026-05", "2026-06"])
    assert LocalWikiStore(root=tmp_path / "wiki").exists("finance/subscription.md")
    assert agent.should_run(quarter="2026-Q2") is False


def test_manual_accounting_rerun_uses_runtime_without_reescalation(monkeypatch):
    runtime = MagicMock()
    monkeypatch.setattr("company_brain.runtime.get_runtime", lambda: runtime)
    agent = RequestManualAccountingAgent(MagicMock())

    agent._rerun_source("finance_monthly_expense", "2026-06")

    runtime.run.assert_called_once_with(
        MonthlyExpenseManager,
        agent.config,
        once=True,
        month="2026-06",
        escalate=False,
    )


def test_manual_accounting_quarterly_rerun_uses_runtime(monkeypatch):
    runtime = MagicMock()
    monkeypatch.setattr("company_brain.runtime.get_runtime", lambda: runtime)
    agent = RequestManualAccountingAgent(MagicMock())

    agent._rerun_source("finance_quarterly_calculation", "2026-Q2")

    runtime.run.assert_called_once_with(
        QuarterlyCalculationManager,
        agent.config,
        once=True,
        quarter="2026-Q2",
        escalate=False,
    )


def test_manual_accounting_completion_requires_checklist_rows():
    assert RequestManualAccountingAgent._is_complete("# Manual Accounting\n\nNo rows") is False
    assert (
        RequestManualAccountingAgent._is_complete(
            "- [ ] Vendor | $10 | 2026-06-01 | category: ___ | note: ___"
        )
        is False
    )
    assert (
        RequestManualAccountingAgent._is_complete(
            "- [ ] Vendor | $10 | 2026-06-01 | category: Software | note: ___"
        )
        is True
    )


def test_manual_accounting_nonblocking_request_marks_gate_after_write(tmp_path, monkeypatch):
    agent = RequestManualAccountingAgent(MagicMock())
    agent._state = StateStore(path=tmp_path / "state.json")
    agent._post_request = MagicMock()  # type: ignore[method-assign]
    monkeypatch.setattr(
        notion_pages,
        "ensure_page",
        lambda *args: "finance/manual-accounting.md",
    )
    monkeypatch.setattr(notion_pages, "update_page_body", lambda *args: True)
    kwargs = {
        "source_agent": "finance_monthly_expense",
        "context": {"period": "2026-06"},
        "uncategorized": [{"name": "Vendor", "amount": -10, "date": "2026-06-01"}],
    }

    result = agent.run(**kwargs, wait_for_completion=False)

    assert result["status"] == "requested"
    assert agent.should_run(**kwargs) is False


def test_finance_managers_stay_idle_during_fleet_pause(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANY_BRAIN_STATE_PATH", str(tmp_path / "state.json"))
    request_pause()

    monthly = MonthlyExpenseManager(MagicMock()).run_once("2026-06")
    quarterly = QuarterlyCalculationManager(MagicMock()).run_once("2026-Q2")

    assert monthly["reason"] == "fleet_paused"
    assert quarterly["reason"] == "fleet_paused"
