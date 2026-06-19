"""Unit tests for Gmail routing records on the wiki volume."""

from pathlib import Path

from company_brain.agents.operations.shared.routing import RoutingStore, new_record


def test_routing_store_roundtrip(tmp_path: Path):
    store = RoutingStore(wiki_dir=tmp_path)
    rec = new_record(
        message_id="abc123",
        thread_id="t1",
        mailbox="me",
        attention="2. Reply",
        domain_tags=["Customer"],
        extracted={"subject": "Hello"},
    )
    store.write(rec)
    assert store.exists("me", "abc123")
    loaded = store.read("me", "abc123")
    assert loaded is not None
    assert loaded.attention == "2. Reply"
    assert loaded.domain_tags == ["Customer"]


def test_mark_handled(tmp_path: Path):
    store = RoutingStore(wiki_dir=tmp_path)
    rec = new_record(
        message_id="m2",
        thread_id="t2",
        mailbox="me",
        attention="1. Action",
        domain_tags=[],
    )
    store.write(rec)
    store.mark_handled(rec, "inbox_sweep")
    loaded = store.read("me", "m2")
    assert loaded is not None
    assert "inbox_sweep" in loaded.handled
