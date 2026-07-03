"""Tests for connection agent writing CRM contact entities."""

from unittest.mock import patch

from company_brain.agents.operations.gmail.connection import ConnectionAgent
from company_brain.agents.operations.shared.routing import RoutingStore, new_record
from company_brain.config import load_config
from company_brain.crm.seeds import ensure_crm_seeds
from company_brain.wiki.store import LocalWikiStore


def test_connection_writes_contact_entity(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setenv("GMAIL_PROFILE", "executive_assistant")
    ensure_crm_seeds()

    store = RoutingStore(wiki_dir=wiki)
    store.write(
        new_record(
            message_id="p1",
            thread_id="t1",
            mailbox="me",
            attention=None,
            domain_tags=["People"],
            extracted={
                "subject": "Great meeting you",
                "from": "Alex Chen <alex@startup.io>",
                "date": "2026-07-02",
            },
        )
    )

    config = load_config()
    agent = ConnectionAgent(config, mailbox="me")
    message = {
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Great meeting you"},
                {"name": "From", "value": "Alex Chen <alex@startup.io>"},
            ]
        },
        "snippet": "Nice to meet you at the conference.",
    }

    with patch(
        "company_brain.agents.operations.gmail.connection.rest.get_message",
        return_value=message,
    ):
        with patch(
            "company_brain.crm.contacts.default_connection_employee",
            return_value="nicky",
        ):
            result = agent.run()

    assert result["updated"] == 1
    wiki_store = LocalWikiStore(root=wiki)
    assert wiki_store.exists("crm/contact/alex-startup-io.md")
    body = wiki_store.read("crm/contact/alex-startup-io.md").body
    assert "Great meeting you" in body
    assert wiki_store.read("crm/contact/alex-startup-io.md").frontmatter["segment"] == "connection"
