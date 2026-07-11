"""Tests for Slack ingest triage, events router, and open threads."""

from unittest.mock import MagicMock, patch

from company_brain.agents.operations.slack.events_router import SlackEventsRouter
from company_brain.agents.operations.slack.ingest_triage import IngestTriageAgent
from company_brain.agents.operations.slack.open_thread_monitor import OpenThreadMonitorAgent
from company_brain.agents.operations.slack.open_threads import (
    handle_reaction_added,
    is_ack_reaction,
    is_done_reaction,
)
from company_brain.agents.operations.slack.routing import SlackRoutingStore
from company_brain.agents.operations.slack.triage_heuristics import classify_tier0


def test_classify_tier0_action_item():
    result = classify_tier0(
        {"text": "TODO: ship docs", "user": "U1", "ts": "1.0"},
        channel_id="C1",
    )
    assert result.urgency == "immediate"
    assert result.kind == "action_pending"
    assert result.dispatch_action_items is True


def test_classify_tier0_mention():
    result = classify_tier0(
        {"text": "hey <@U2> can you review?", "user": "U1", "ts": "1.0"},
        channel_id="C1",
    )
    assert result.kind == "discussion_pending"
    assert "U2" in result.assignees


def test_classify_tier0_out_of_scope(tmp_path, monkeypatch):
    from company_brain.agents.operations.slack import channels_config

    registry = tmp_path / "slack_channels.json"
    registry.write_text(
        '{"version":1,"channels":{"C9":{"ingest_mode":"out_of_scope","name":"memes"}}}'
    )
    monkeypatch.setattr(channels_config, "CHANNELS_FILE", registry)

    result = classify_tier0({"text": "hello", "user": "U1", "ts": "1"}, channel_id="C9")
    assert result.urgency == "skip"


def test_ingest_triage_writes_routing_record(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.routing.resolve_wiki_dir",
        lambda: wiki,
    )
    with patch(
        "company_brain.agents.operations.slack.ingest_triage.slack_client.bot_user_id",
        return_value="UBOT",
    ):
        agent = IngestTriageAgent(MagicMock())
        result = agent.process_message(
            "C1",
            {"text": "<@U2> please reply", "user": "U1", "ts": "10.1"},
        )
    assert result["status"] == "routed"
    store = SlackRoutingStore(wiki_dir=wiki)
    record = store.read("C1", "10.1")
    assert record is not None
    assert record.kind == "discussion_pending"


def test_events_router_url_verification():
    router = SlackEventsRouter(MagicMock())
    out = router.handle_payload({"type": "url_verification", "challenge": "abc"})
    assert out["challenge"] == "abc"


def test_events_router_message_dispatches_triage(monkeypatch):
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.ingest_triage.SlackRoutingStore",
        lambda: MagicMock(),
    )
    router = SlackEventsRouter(MagicMock())
    with patch.object(
        IngestTriageAgent,
        "process_message",
        return_value={"status": "routed"},
    ) as mock_process:
        result = router.handle_payload(
            {
                "type": "event_callback",
                "event": {
                    "type": "message",
                    "channel": "C1",
                    "text": "TODO: fix",
                    "user": "U1",
                    "ts": "1.0",
                },
            }
        )
    assert result["status"] == "routed"
    mock_process.assert_called_once()


def test_reaction_ack_and_done(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.routing.resolve_wiki_dir",
        lambda: wiki,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.open_threads.load_members_config",
        lambda: MagicMock(active_members=lambda: {}),
    )
    store = SlackRoutingStore(wiki_dir=wiki)
    store.upsert("C1", "1.0", kind="discussion_pending", assignees=["U2"])

    with patch(
        "company_brain.agents.operations.slack.open_thread_monitor.slack_client.permalink",
        return_value="",
    ):
        ack = handle_reaction_added(
            channel_id="C1",
            thread_ts="1.0",
            reaction="thumbsup",
            user_id="U2",
            routing=store,
        )
        assert ack["status"] == "acknowledged"
        record = store.read("C1", "1.0")
        assert record is not None
        assert record.handled.get("read_reaction") == "thumbsup"

        done = handle_reaction_added(
            channel_id="C1",
            thread_ts="1.0",
            reaction="white_check_mark",
            user_id="U2",
            routing=store,
        )
    assert done["status"] == "closed"
    record = store.read("C1", "1.0")
    assert record is not None
    assert record.handled.get("closed") == "white_check_mark"


def test_reaction_name_helpers():
    assert is_ack_reaction("thumbsup")
    assert is_done_reaction("white_check_mark")


def test_open_thread_monitor_refreshes_members(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    emp = tmp_path / "employee_wiki"
    wiki.mkdir()
    emp.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.routing.resolve_wiki_dir",
        lambda: wiki,
    )
    monkeypatch.setattr(
        "company_brain.wiki.employee_store.resolve_employee_wiki_dir",
        lambda: emp,
    )

    members = MagicMock()
    members.active_members.return_value = {"alice": MagicMock()}
    members.get.return_value = MagicMock(bindings=MagicMock(slack_user_id="U2"))
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.open_threads.load_members_config",
        lambda: members,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.open_thread_monitor.load_members_config",
        lambda: members,
    )

    store = SlackRoutingStore(wiki_dir=wiki)
    store.upsert("#ops", "1.0", kind="discussion_pending", assignees=["U2"])

    with patch(
        "company_brain.agents.operations.slack.open_thread_monitor.slack_client.permalink",
        return_value="https://slack/thread",
    ):
        result = OpenThreadMonitorAgent(MagicMock()).run()

    assert result["members"] == 1
    page = emp / "alice" / "open-thread.md"
    assert page.exists()
    assert "Open Threads" in page.read_text()
