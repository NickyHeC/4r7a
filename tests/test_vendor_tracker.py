"""Tests for vendor_tracker finance wiki paths."""

from unittest.mock import patch

from company_brain.agents.operations.gmail.vendor_tracker import VendorTrackerAgent, _vendor_slug
from company_brain.agents.operations.shared.routing import RoutingStore, new_record
from company_brain.config import load_config
from company_brain.wiki.store import LocalWikiStore


def test_vendor_slug_from_domain():
    assert _vendor_slug("Billing <billing@stripe.com>") == "stripe.com"


def test_vendor_tracker_writes_finance_vendor_page(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))

    store = RoutingStore(wiki_dir=wiki)
    store.write(
        new_record(
            message_id="v1",
            thread_id="t1",
            mailbox="me",
            attention="3. FYI",
            domain_tags=["Vendor"],
            extracted={
                "subject": "Your plan renewal",
                "from": "Billing <billing@stripe.com>",
            },
        )
    )

    agent = VendorTrackerAgent(load_config(), mailbox="me")
    message = {
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Your plan renewal"},
                {"name": "From", "value": "Billing <billing@stripe.com>"},
            ]
        },
        "snippet": "renewal notice",
    }

    with patch(
        "company_brain.agents.operations.gmail.vendor_tracker.rest.get_message",
        return_value=message,
    ):
        result = agent.run()

    assert result["updated"] == 1
    wiki_store = LocalWikiStore(root=wiki)
    assert wiki_store.exists("finance/vendor/stripe.com.md")
    doc = wiki_store.read("finance/vendor/stripe.com.md")
    assert doc.frontmatter.get("section") == "finance"
    assert "Your plan renewal" in doc.body
