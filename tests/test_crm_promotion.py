"""Tests for CRM two-way promotion."""

from __future__ import annotations

import base64
from unittest.mock import patch

from company_brain.agents.operations.shared.routing import RoutingStore, new_record
from company_brain.crm.promotion import (
    is_dismissive_outbound,
    thread_is_two_way,
    try_promote_thread_on_sent,
)
from company_brain.crm.seeds import ensure_crm_seeds
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


def _plain_body_message(body: str, *, from_: str = "Me <me@company.com>") -> dict:
    data = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    return {
        "payload": {
            "headers": [{"name": "From", "value": from_}],
            "mimeType": "text/plain",
            "body": {"data": data},
        },
        "snippet": body,
    }


def test_is_dismissive_outbound():
    assert is_dismissive_outbound(_plain_body_message("Thanks, not interested."))
    assert not is_dismissive_outbound(
        _plain_body_message("Happy to explore a partnership next week.")
    )


def test_thread_is_two_way():
    thread = {
        "messages": [
            {
                "labelIds": ["INBOX"],
                "payload": {"headers": [{"name": "From", "value": "Them <them@startup.io>"}]},
            },
            {
                "labelIds": ["SENT"],
                "payload": {"headers": [{"name": "From", "value": "Me <me@company.com>"}]},
            },
        ]
    }
    with patch("company_brain.crm.promotion.rest.mailbox_email", return_value="me@company.com"):
        assert thread_is_two_way(thread, mailbox="me")


def test_promote_creates_connection_contact(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    ensure_crm_seeds()

    store = RoutingStore(wiki_dir=wiki)
    store.write(
        new_record(
            message_id="in1",
            thread_id="thread-promo",
            mailbox="me",
            attention=None,
            domain_tags=["Cold Inbound/Partnership"],
            extracted={"from": "Them <them@startup.io>", "subject": "Partnership"},
        )
    )

    wiki_store = LocalWikiStore(root=wiki)
    wiki_store.write(
        "crm/inbound/partnership/2026-07-02-test.md",
        MarkdownDoc(
            frontmatter={
                "title": "Partnership",
                "thread_id": "thread-promo",
                "status": "open",
            },
            body="preview",
        ),
    )

    thread = {
        "messages": [
            {
                "labelIds": ["INBOX"],
                "payload": {"headers": [{"name": "From", "value": "Them <them@startup.io>"}]},
            },
            {
                "labelIds": ["SENT"],
                "payload": {"headers": [{"name": "From", "value": "Me <me@company.com>"}]},
            },
        ]
    }
    sent = _plain_body_message("Let's schedule a call to discuss integration.")

    with patch("company_brain.crm.promotion.rest.mailbox_email", return_value="me@company.com"):
        with patch("company_brain.crm.promotion.rest.get_thread", return_value=thread):
            with patch(
                "company_brain.crm.promotion.default_connection_employee",
                return_value="nicky",
            ):
                result = try_promote_thread_on_sent(
                    mailbox="me",
                    thread_id="thread-promo",
                    sent_message=sent,
                    store=store,
                )

    assert result["promoted"] is True
    assert result["slug"] == "them-startup-io"
    wiki_store = LocalWikiStore(root=wiki)
    contact = wiki_store.read("crm/contact/them-startup-io.md")
    assert contact.frontmatter["segment"] == "connection"
    assert (
        wiki_store.read("crm/inbound/partnership/2026-07-02-test.md").frontmatter["status"]
        == "promoted"
    )
    log = wiki_store.read("crm/promotion-log.md").body
    assert "them-startup-io" in log
    assert "thread-promo" in log


def test_promote_skips_protected_investor_segment(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    ensure_crm_seeds()

    wiki_store = LocalWikiStore(root=wiki)
    wiki_store.write(
        "crm/contact/them-startup-io.md",
        MarkdownDoc(
            frontmatter={
                "title": "Them",
                "segment": "investor",
                "canonical_email": "them@startup.io",
            },
            body="## Interactions\n",
        ),
    )
    from company_brain.crm.registry import rebuild_registry

    rebuild_registry()

    store = RoutingStore(wiki_dir=wiki)
    store.write(
        new_record(
            message_id="in2",
            thread_id="thread-inv",
            mailbox="me",
            attention=None,
            domain_tags=["Cold Inbound/Investor Interest"],
            extracted={"from": "Them <them@startup.io>"},
        )
    )

    thread = {
        "messages": [
            {
                "labelIds": ["INBOX"],
                "payload": {"headers": [{"name": "From", "value": "Them <them@startup.io>"}]},
            },
            {
                "labelIds": ["SENT"],
                "payload": {"headers": [{"name": "From", "value": "Me <me@company.com>"}]},
            },
        ]
    }
    sent = _plain_body_message("Great to connect about the round.")

    with patch("company_brain.crm.promotion.rest.mailbox_email", return_value="me@company.com"):
        with patch("company_brain.crm.promotion.rest.get_thread", return_value=thread):
            result = try_promote_thread_on_sent(
                mailbox="me",
                thread_id="thread-inv",
                sent_message=sent,
                store=store,
            )

    assert result["promoted"] is False
    assert result["reason"] == "protected_segment:investor"
