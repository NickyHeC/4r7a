"""Tests for CRM inbound retention (inbox_sweep integration)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from company_brain.agents.operations.gmail.inbox_sweep import InboxSweepAgent
from company_brain.agents.operations.shared.routing import RoutingStore, new_record
from company_brain.config import load_config
from company_brain.crm.retention import (
    crm_inbound_archive_due,
    triaged_at_older_than,
)


def _record(*, triaged_at: str, handled: bool = True):
    rec = new_record(
        message_id="msg-ret",
        thread_id="thread-ret",
        mailbox="me",
        attention=None,
        domain_tags=["Cold Inbound/Partnership"],
    )
    rec.triaged_at = triaged_at
    if handled:
        rec.handled["inbound_crm"] = triaged_at
    return rec


def test_triaged_at_older_than_calendar_days():
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert triaged_at_older_than(_record(triaged_at=old), days=7)
    assert not triaged_at_older_than(_record(triaged_at=recent), days=7)


def test_crm_inbound_archive_due_requires_handled():
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    assert not crm_inbound_archive_due(_record(triaged_at=old, handled=False))


def test_crm_inbound_archive_due_when_old_and_handled():
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    assert crm_inbound_archive_due(_record(triaged_at=old, handled=True))


def test_inbox_sweep_archives_old_crm_inbound(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))

    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    store = RoutingStore(wiki_dir=wiki)
    store.write(_record(triaged_at=old, handled=True))

    agent = InboxSweepAgent(load_config(), mailbox="me")
    message = {"labelIds": ["INBOX"], "internalDate": "0"}

    with patch(
        "company_brain.agents.operations.gmail.inbox_sweep.rest.get_message",
        return_value=message,
    ):
        with patch(
            "company_brain.agents.operations.gmail.inbox_sweep.rest.is_in_inbox",
            return_value=True,
        ):
            with patch("company_brain.agents.operations.gmail.inbox_sweep.archive") as archive_mock:
                result = agent.run()

    assert result["archived"] == 1
    archive_mock.assert_called_once_with("msg-ret", mailbox="me")


def test_inbox_sweep_keeps_recent_crm_inbound(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))

    recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    store = RoutingStore(wiki_dir=wiki)
    store.write(_record(triaged_at=recent, handled=True))

    agent = InboxSweepAgent(load_config(), mailbox="me")
    message = {"labelIds": ["INBOX"], "internalDate": "0"}

    with patch(
        "company_brain.agents.operations.gmail.inbox_sweep.rest.get_message",
        return_value=message,
    ):
        with patch(
            "company_brain.agents.operations.gmail.inbox_sweep.rest.is_in_inbox",
            return_value=True,
        ):
            with patch("company_brain.agents.operations.gmail.inbox_sweep.archive") as archive_mock:
                result = agent.run()

    assert result["archived"] == 0
    archive_mock.assert_not_called()
