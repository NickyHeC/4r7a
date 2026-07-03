"""Tests for inbound_crm agent (press + events → wiki + selective Slack)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from company_brain.agents.operations.gmail.inbound_crm import SPECIALIST_KEY, InboundCrmAgent
from company_brain.agents.operations.shared.routing import RoutingRecord, RoutingStore, new_record
from company_brain.config import load_config
from company_brain.crm.seeds import ensure_crm_seeds
from company_brain.wiki.store import LocalWikiStore


def _record(*, tag: str, message_id: str = "msg1") -> RoutingRecord:
    return new_record(
        message_id=message_id,
        thread_id="thread1",
        mailbox="me",
        attention=None,
        domain_tags=[tag],
        extracted={
            "subject": "Podcast invite from Major Press",
            "from": "Host <host@majorpress.com>",
            "date": "2026-07-02",
        },
    )


def test_inbound_crm_writes_wiki_and_alerts_high_score(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    ensure_crm_seeds()

    store = RoutingStore(wiki_dir=wiki)
    store.write(_record(tag="Cold Inbound/Press & Podcast"))

    config = load_config()
    agent = InboundCrmAgent(config, mailbox="me")

    message = {
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Podcast invite from Major Press"},
                {"name": "From", "value": "Host <host@majorpress.com>"},
            ]
        },
        "snippet": "podcast interview media press",
    }

    emitted: list[str] = []

    def capture(signal):
        emitted.append(signal.text)

    agent._notifier = MagicMock()
    agent._notifier.emit = capture

    with patch(
        "company_brain.agents.operations.gmail.inbound_crm.rest.get_message",
        return_value=message,
    ):
        with patch(
            "company_brain.agents.operations.shared.inbound_score.reputable_domains",
            lambda: {"majorpress.com"},
        ):
            result = agent.run()

    assert result["written"] == 1
    assert result["slack_alerts"] == 1
    assert len(emitted) == 1

    wiki_store = LocalWikiStore(root=wiki)
    pages = wiki_store.list("crm/inbound/press-podcast")
    assert len(pages) == 1
    doc = wiki_store.read(pages[0])
    assert doc.frontmatter["inbound_type"] == "press-podcast"
    assert doc.frontmatter["slack_notified"] is True
    assert doc.frontmatter["score"] >= 6

    updated = store.read("me", "msg1")
    assert SPECIALIST_KEY in updated.handled


def test_inbound_crm_skips_low_score_slack(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    ensure_crm_seeds()

    store = RoutingStore(wiki_dir=wiki)
    store.write(
        _record(
            tag="Cold Inbound/Event Invitations",
            message_id="msg2",
        )
    )

    config = load_config()
    agent = InboundCrmAgent(config, mailbox="me")
    agent._notifier = MagicMock()

    message = {
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Quick question"},
                {"name": "From", "value": "Sam <sam@gmail.com>"},
            ]
        },
        "snippet": "reaching out",
    }

    with patch(
        "company_brain.agents.operations.gmail.inbound_crm.rest.get_message",
        return_value=message,
    ):
        result = agent.run()

    assert result["written"] == 1
    assert result["slack_alerts"] == 0
    agent._notifier.emit.assert_not_called()

    wiki_store = LocalWikiStore(root=wiki)
    pages = wiki_store.list("crm/inbound/event-invitation")
    assert wiki_store.read(pages[0]).frontmatter["slack_notified"] is False


def test_inbound_crm_writes_partnership_without_slack(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    ensure_crm_seeds()

    store = RoutingStore(wiki_dir=wiki)
    store.write(
        new_record(
            message_id="msg3",
            thread_id="thread3",
            mailbox="me",
            attention=None,
            domain_tags=["Cold Inbound/Partnership"],
            extracted={
                "subject": "API integration partnership",
                "from": "Biz <biz@partner.io>",
                "date": "2026-07-02",
            },
        )
    )

    config = load_config()
    agent = InboundCrmAgent(config, mailbox="me")
    agent._notifier = MagicMock()

    message = {
        "payload": {
            "headers": [
                {"name": "Subject", "value": "API integration partnership"},
                {"name": "From", "value": "Biz <biz@partner.io>"},
            ]
        },
        "snippet": "strategic b2b saas integration partnership",
    }

    with patch(
        "company_brain.agents.operations.gmail.inbound_crm.rest.get_message",
        return_value=message,
    ):
        result = agent.run()

    assert result["written"] == 1
    assert result["slack_alerts"] == 0
    agent._notifier.emit.assert_not_called()

    wiki_store = LocalWikiStore(root=wiki)
    pages = wiki_store.list("crm/inbound/partnership")
    assert len(pages) == 1
    assert wiki_store.read(pages[0]).frontmatter["inbound_type"] == "partnership"
