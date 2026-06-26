"""Unit tests for stale audit and manual management."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from company_brain.agents.engineering.linear.request_manual_management import (
    RequestManualManagementAgent,
)
from company_brain.agents.engineering.linear.stale_audit import StaleAuditAgent
from company_brain.agents.engineering.linear.task_bindings import TaskBindingStore
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


def test_manual_checklist_complete_detection():
    content = """
## Manual Management
- [x] ENG-1 | Fix | current: In Progress | proposed: Done | note: ok
"""
    assert RequestManualManagementAgent._is_complete(content) is True

    incomplete = """
- [ ] ENG-2 | T | current: Todo | proposed: ___ | note: ___
"""
    assert RequestManualManagementAgent._is_complete(incomplete) is False


def test_stale_audit_finds_old_issues(tmp_path: Path):
    config = MagicMock()
    agent = StaleAuditAgent(config)
    old = "2020-01-01T00:00:00.000Z"
    issues = [{
        "id": "1",
        "identifier": "ENG-99",
        "title": "Stale task",
        "updatedAt": old,
        "state": {"name": "In Progress", "id": "s1"},
    }]

    with patch(
        "company_brain.agents.engineering.linear.stale_audit.linear_client.list_open_issues",
        return_value=issues,
    ), patch(
        "company_brain.agents.engineering.linear.stale_audit.linear_client.linear_is_configured",
        return_value=True,
    ), patch(
        "company_brain.runtime.get_runtime",
    ) as mock_rt:
        mock_rt.return_value.run.return_value = {"status": "requested"}
        result = agent.run(dispatch_manual=True, sync=False)

    assert result["proposals"] == 1


def test_apply_approved_status(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    store = TaskBindingStore(config_dir=config_dir)
    store.create_gmail_binding(
        message_id="m1",
        thread_id="t1",
        mailbox="me",
        linear_issue={"id": "uuid-1", "identifier": "ENG-5", "url": ""},
        title="Task",
        mirror_wiki=False,
    )

    wiki = LocalWikiStore(root=tmp_path / "wiki")
    checklist = (
        "## Manual\n\n"
        "- [x] ENG-5 | Task | current: In Progress | proposed: Done | note: ok\n"
    )
    wiki.write(
        "engineering/linear/manual-management.md",
        MarkdownDoc(frontmatter={"title": "Linear Manual Management"}, body=checklist),
    )

    config = MagicMock()
    agent = RequestManualManagementAgent(config)
    agent._bindings = store

    with patch(
        "company_brain.agents.engineering.linear.request_manual_management.read_wiki_page",
        return_value=checklist,
    ), patch(
        "company_brain.agents.engineering.linear.request_manual_management.linear_client.resolve_state_id",
        return_value="state-done",
    ), patch(
        "company_brain.agents.engineering.linear.request_manual_management.linear_client.update_issue",
        return_value={"id": "uuid-1", "identifier": "ENG-5"},
    ):
        applied = agent._apply_approved()

    assert len(applied) == 1
    assert applied[0]["identifier"] == "ENG-5"


def test_linear_onboarding_backfill(tmp_path: Path, monkeypatch):
    wiki = tmp_path / "wiki"
    routing = wiki / "operations/gmail/routing/me"
    routing.mkdir(parents=True)
    import json

    (routing / "msg1.json").write_text(json.dumps({
        "message_id": "msg1",
        "thread_id": "t1",
        "mailbox": "me",
        "triaged_at": "2026-01-01T00:00:00+00:00",
        "attention": "1. Action",
        "domain_tags": [],
        "extracted": {
            "linear_issue_id": "ENG-10",
            "linear_issue_url": "https://linear.app/x/ENG-10",
            "subject": "Backfill me",
        },
        "handled": {},
        "disposition": {},
    }))

    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.engineering.linear.task_bindings.CONFIG_DIR",
        config_dir,
    )

    from company_brain.agents.engineering.linear.linear_onboarding import LinearOnboardingAgent

    with patch(
        "company_brain.agents.engineering.linear.linear_onboarding.linear_client.list_teams",
        return_value=[],
    ), patch(
        "company_brain.agents.engineering.linear.linear_onboarding.linear_client.get_issue",
        return_value={"id": "u10", "identifier": "ENG-10", "url": "https://linear.app/x/ENG-10"},
    ), patch(
        "company_brain.agents.engineering.linear.linear_onboarding.linear_client.linear_is_configured",
        return_value=True,
    ), patch.object(
        LinearOnboardingAgent, "_run_structure_proposal", return_value={},
    ), patch.object(
        LinearOnboardingAgent, "_run_slot_check", return_value={},
    ), patch.object(LinearOnboardingAgent, "_start_manager"):
        agent = LinearOnboardingAgent(MagicMock())
        result = agent.run(start_manager=False)

    assert result["bindings_backfilled"] == 1
    bindings = TaskBindingStore(config_dir=config_dir)
    assert bindings.find_by_gmail_message("msg1") is not None
