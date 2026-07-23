"""Tests for Slack action items, thread watcher, manager, and routing store."""

from unittest.mock import MagicMock, patch

from company_brain.agents.engineering.linear.linear_completed.dispatcher import (
    LinearCompletedAgent,
)
from company_brain.agents.engineering.linear.linear_completed.slack_thread_respond import (
    SlackThreadRespondAgent,
)
from company_brain.agents.engineering.linear.task_bindings import TaskBinding, TaskBindingStore
from company_brain.agents.operations.slack.action_items import (
    ActionItemsAgent,
    extract_action_title,
    message_has_action_item,
)
from company_brain.agents.operations.slack.routing import SlackRoutingStore
from company_brain.agents.operations.slack.thread_watcher import ThreadWatcherAgent
from company_brain.agents.operations.slack_manager import SlackManager


def test_message_has_action_item():
    assert message_has_action_item("TODO: ship the doc") is True
    assert message_has_action_item("Thanks!") is False


def test_extract_action_title():
    title = extract_action_title("- [ ] Alice will send the deck by Friday")
    assert "Alice" in title


def test_action_items_creates_binding(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.engineering.linear.task_bindings.CONFIG_DIR",
        config_dir,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.routing.resolve_wiki_dir",
        lambda: wiki,
    )
    config = MagicMock()
    agent = ActionItemsAgent(config)

    with (
        patch(
            "company_brain.agents.operations.slack.action_items.linear_client.create_issue",
            return_value={"id": "l1", "identifier": "ENG-7", "url": "https://linear/x"},
        ),
        patch(
            "company_brain.agents.operations.slack.action_items.task_class_fan_out",
            return_value=["linear", "slack"],
        ),
        patch(
            "company_brain.agents.operations.slack.action_items.slack_client.permalink",
            return_value="https://slack/x",
        ),
    ):
        result = agent.run(
            channel="#team-ops",
            thread_ts="1000.1",
            message_ts="1000.2",
            text="Action item: update the wiki",
        )

    assert result["status"] == "created"
    store = TaskBindingStore(config_dir=config_dir)
    assert store.find_by_slack_thread("#team-ops", "1000.1") is not None


def test_slack_thread_respond_posts_reply(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.engineering.linear.task_bindings.CONFIG_DIR",
        config_dir,
    )
    store = TaskBindingStore(config_dir=config_dir)
    binding = store.create_slack_binding(
        channel="#team-ops",
        thread_ts="2000.1",
        message_ts="2000.2",
        linear_issue={"id": "l2", "identifier": "ENG-8", "url": "https://linear/8"},
        title="Slack task",
        mirror_wiki=False,
    )
    agent = SlackThreadRespondAgent(MagicMock())

    with patch(
        "company_brain.agents.operations.slack.slack_client.post_thread_reply",
        return_value="3000.1",
    ):
        result = agent.run(binding=binding, linear_status="Done")

    assert result["status"] == "replied"
    updated = store.find_by_slack_thread("#team-ops", "2000.1")
    assert updated is not None
    assert updated.platforms["slack"]["replied"] is True


def test_linear_completed_routes_slack():
    binding = TaskBinding(
        task_id="t1",
        origin={"platform": "slack", "artifact_id": "a", "department": "operations"},
        linear={"issue_id": "l", "identifier": "ENG-9", "url": ""},
        platforms={"slack": {"channel": "#team-ops", "thread_ts": "1", "message_ts": "2"}},
        task_class="slack_action",
        title="Test",
    )
    agent = LinearCompletedAgent(MagicMock())
    agent._bindings = MagicMock()
    agent._bindings.get.return_value = binding

    with (
        patch(
            "company_brain.agents.engineering.linear.linear_completed.dispatcher.task_class_fan_out",
            return_value=["linear", "slack"],
        ),
        patch(
            "company_brain.agents.engineering.linear.linear_completed.slack_thread_respond.SlackThreadRespondAgent"
        ) as mock_cls,
    ):
        mock_cls.return_value.execute.return_value = {"status": "replied"}
        result = agent.run(task_id="t1", linear_issue={"state": {"name": "Done"}})

    assert result["platforms"]["slack"]["status"] == "replied"


def test_thread_watcher_dispatches_on_action_item():
    agent = ThreadWatcherAgent(MagicMock())
    msg = {"ts": "1.1", "text": "TODO: fix onboarding"}

    with (
        patch(
            "company_brain.agents.operations.slack.thread_watcher.cfg.watched_channels",
            return_value=["#team-ops"],
        ),
        patch(
            "company_brain.agents.operations.slack.thread_watcher.slack_client.resolve_channel_id",
            return_value="C1",
        ),
        patch(
            "company_brain.agents.operations.slack.thread_watcher.channels_config.is_out_of_scope",
            return_value=False,
        ),
        patch.object(agent, "_since_timestamp", return_value=MagicMock()),
        patch(
            "company_brain.agents.operations.slack.thread_watcher.slack_client.fetch_channel_messages",
            return_value=[msg],
        ),
        patch(
            "company_brain.agents.operations.slack.thread_watcher.slack_client.datetime_to_slack_ts",
            return_value=0.0,
        ),
        patch.object(agent._triage, "process_message", return_value={"status": "routed"}),
        patch(
            "company_brain.agents.operations.slack.thread_watcher.is_handled",
            return_value=False,
        ),
        patch(
            "company_brain.agents.operations.slack.thread_watcher.mark_handled",
        ),
        patch.object(
            agent,
            "_dispatch_action_items",
            return_value={"status": "created"},
        ) as mock_dispatch,
    ):
        scanned, hits, triaged = agent._scan_channel("#team-ops")

    assert scanned == 1
    assert hits == 1
    assert triaged == 1
    mock_dispatch.assert_called_once()


def test_slack_routing_store_roundtrip(tmp_path):
    wiki = tmp_path / "wiki"
    store = SlackRoutingStore(wiki_dir=wiki)
    record = store.upsert(
        "#team-ops",
        "1234.5678",
        kind="action_pending",
        attention="1. Action",
    )
    assert record.channel == "#team-ops"
    loaded = store.read("#team-ops", "1234.5678")
    assert loaded is not None
    assert loaded.kind == "action_pending"
    store.mark_handled(loaded, "action_items")
    again = store.read("#team-ops", "1234.5678")
    assert again is not None
    assert "action_items" in again.handled


def test_slack_manager_dispatches_thread_watcher(monkeypatch):
    manager = SlackManager(MagicMock())
    mock_runtime = MagicMock()

    with (
        patch("company_brain.runtime.get_runtime", return_value=mock_runtime),
        patch.object(manager, "_should_run_channel_registry", return_value=False),
        patch.object(manager, "_should_run_thread_absorb", return_value=False),
        patch.object(manager, "_should_run_who_knows", return_value=False),
    ):
        import asyncio

        asyncio.run(manager._run_pass())

    assert mock_runtime.run.call_count == 3


def test_wiki_bot_token_fallback(monkeypatch):
    from company_brain.agents.operations.slack import slack_client

    monkeypatch.delenv("SLACK_WIKI_BOT_TOKEN", raising=False)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-legacy")
    assert slack_client.wiki_bot_token() == "xoxb-legacy"

    monkeypatch.setenv("SLACK_WIKI_BOT_TOKEN", "xoxb-wiki")
    assert slack_client.wiki_bot_token() == "xoxb-wiki"
