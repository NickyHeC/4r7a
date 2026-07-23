"""Cheap cost-gate coverage for LLM and web-search specialists."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from company_brain.agents.admin.investor_newsletter import InvestorNewsletterAgent
from company_brain.agents.engineering.github_manager import GitHubManager
from company_brain.agents.finance.ramp.card_spend import RampCardSpendAgent, _cache_key
from company_brain.agents.finance.request_manual_accounting import (
    RequestManualAccountingAgent,
)
from company_brain.agents.gates import StateStore
from company_brain.agents.growth.content.draft_writer import DraftWriterAgent
from company_brain.agents.hr.linkedin.pull import DUE_PREFIX, PullAgent
from company_brain.agents.operations.gmail.draft_reply import (
    DraftReplyAgent,
    _candidate_signature,
)
from company_brain.agents.product.update.product_update import ProductUpdateAgent
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


def test_product_update_gate_skips_existing_month(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    LocalWikiStore(root=wiki).write(
        "product/update/newsletter/2026-07.md",
        MarkdownDoc(frontmatter={"title": "Product Update 2026-07"}, body="draft"),
    )
    agent = ProductUpdateAgent(MagicMock())
    assert agent.should_run(month="2026-07") is False
    assert agent.should_run(month="2026-07", force=True) is True


def test_investor_update_gate_skips_existing_month(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    LocalWikiStore(root=wiki).write(
        "admin/investor-newsletter/2026-07.md",
        MarkdownDoc(frontmatter={"title": "Investor Update 2026-07"}, body="draft"),
    )
    agent = InvestorNewsletterAgent(MagicMock())
    assert agent.should_run(month="2026-07") is False
    assert agent.should_run(month="2026-07", force=True) is True


def test_draft_writer_gate_marks_successful_request(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setattr(
        "company_brain.agents.growth.content.draft_writer._compose_draft",
        lambda **kwargs: "A deterministic draft.",
    )
    agent = DraftWriterAgent(MagicMock())
    agent._state = StateStore(path=tmp_path / "state.json")
    kwargs = {"channel": "x", "instructions": "Ship it", "title": "Release"}
    assert agent.should_run(**kwargs) is True
    agent.run(**kwargs)
    assert agent.should_run(**kwargs) is False
    assert agent.should_run(**kwargs, force=True) is True


def test_manual_accounting_gate_deduplicates_same_items(tmp_path):
    agent = RequestManualAccountingAgent(MagicMock())
    agent._state = StateStore(path=tmp_path / "state.json")
    kwargs = {
        "source_agent": "finance_monthly_expense",
        "context": {"period": "2026-07", "kind": "monthly"},
        "uncategorized": [{"name": "Vendor", "amount": -10.0}],
    }
    assert agent.should_run(**kwargs) is True
    key = "manual_accounting:finance_monthly_expense:2026-07"
    from company_brain.agents.finance.request_manual_accounting import _request_gate

    _, signature = _request_gate(**kwargs)
    agent._state.set(key, signature)
    assert agent.should_run(**kwargs) is False


def test_linkedin_gate_is_monthly_per_scope(tmp_path):
    agent = PullAgent(MagicMock())
    agent._state = StateStore(path=tmp_path / "state.json")
    assert agent.should_run(member_key="alice") is True
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    agent._state.set(f"{DUE_PREFIX}alice", month)
    assert agent.should_run(member_key="alice") is False
    assert agent.should_run(member_key="alice", force=True) is True


def test_linkedin_transient_skip_does_not_advance_month(tmp_path):
    agent = PullAgent(MagicMock())
    agent._state = StateStore(path=tmp_path / "state.json")
    agent._pull_one = MagicMock(  # type: ignore[method-assign]
        return_value={"status": "skipped", "reason": "empty_search", "member": "alice"}
    )

    agent.run(member_key="alice")

    assert agent.should_run(member_key="alice") is True


def test_ramp_gate_returns_cached_normalized_result(tmp_path):
    agent = RampCardSpendAgent(MagicMock())
    agent._state = StateStore(path=tmp_path / "state.json")
    cached = {
        "start": "2026-07-01",
        "end": "2026-07-31",
        "transactions": [{"name": "OpenAI", "amount": -20.0}],
        "by_qb_category": {"Software": 20.0},
        "total_spend": 20.0,
    }
    agent._state.set(_cache_key("2026-07-01", "2026-07-31"), cached)
    assert agent.should_run(start="2026-07-01", end="2026-07-31") is False
    assert agent.cost_gate_skip_output(start="2026-07-01", end="2026-07-31") == cached
    assert agent.should_run(start="2026-07-01", end="2026-07-31", force=True) is True


def test_ramp_gate_does_not_cache_invalid_output(tmp_path):
    agent = RampCardSpendAgent(MagicMock())
    agent._state = StateStore(path=tmp_path / "state.json")
    agent._query_ramp = AsyncMock(return_value="not-json")  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="missing JSON markers"):
        agent.run(start="2026-07-01", end="2026-07-31")

    assert agent.should_run(start="2026-07-01", end="2026-07-31") is True


def test_github_manager_does_not_advance_commit_gate_before_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANY_BRAIN_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(
        "company_brain.agents.engineering.github.gh.list_recent_commits",
        lambda repo, since: [{"sha": "abc123"}],
    )
    manager = GitHubManager(MagicMock(), repo="org/repo")
    assert manager._latest_commit_since_last_run() == "abc123"
    assert manager._latest_commit_since_last_run() == "abc123"

    from company_brain.agents.gates import changed_since

    changed_since("github:org/repo:last_commit", "abc123", update=True)
    assert manager._latest_commit_since_last_run() is None


def test_gmail_draft_gate_uses_handled_signature(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANY_BRAIN_STATE_PATH", str(tmp_path / "state.json"))
    records = [MagicMock(message_id="m2"), MagicMock(message_id="m1")]
    agent = DraftReplyAgent(MagicMock(), mailbox="ceo")
    agent._llm_candidates = MagicMock(return_value=records)  # type: ignore[method-assign]
    assert agent.should_run() is True

    from company_brain.agents.gates import mark_handled

    mark_handled("draft_reply:ceo", _candidate_signature(records))
    assert agent.should_run() is False


def test_gmail_draft_skip_is_not_marked_handled(monkeypatch):
    record = MagicMock(message_id="m1", thread_id="t1")
    agent = DraftReplyAgent(MagicMock(), mailbox="ceo")
    agent._llm_candidates = MagicMock(return_value=[record])  # type: ignore[method-assign]
    agent._store = MagicMock()
    agent._create_draft = AsyncMock(return_value=False)  # type: ignore[method-assign]
    monkeypatch.setattr(
        "company_brain.agents.operations.gmail.draft_reply.rest.get_thread",
        lambda thread_id, mailbox: {},
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.gmail.draft_reply.is_simple_reply",
        lambda thread, mailbox: True,
    )

    assert agent.run() == {"drafted": 0, "skipped_complex": 1}
    agent._store.mark_handled.assert_not_called()
