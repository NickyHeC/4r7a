"""Tests for Slack action items and Linear completion reply."""

from unittest.mock import MagicMock, patch

from company_brain.agents.engineering.linear.linear_completed.dispatcher import (
    LinearCompletedAgent,
)
from company_brain.agents.engineering.linear.linear_completed.slack_thread_respond import (
    SlackThreadRespondAgent,
)
from company_brain.agents.engineering.linear.task_bindings import TaskBinding, TaskBindingStore
from company_brain.agents.operations.slack.action_items import (
    extract_action_title,
    message_has_action_item,
)
from company_brain.agents.operations.slack.slack_action_items import SlackActionItemsAgent
from company_brain.agents.operations.slack.slack_thread_watcher import SlackThreadWatcherAgent


def test_message_has_action_item():
    assert message_has_action_item("TODO: ship the doc") is True
    assert message_has_action_item("Thanks!") is False


def test_extract_action_title():
    title = extract_action_title("- [ ] Alice will send the deck by Friday")
    assert "Alice" in title


def test_slack_action_items_creates_binding(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.engineering.linear.task_bindings.CONFIG_DIR",
        config_dir,
    )
    config = MagicMock()
    agent = SlackActionItemsAgent(config)

    with patch(
        "company_brain.agents.operations.slack.slack_action_items.linear_client.create_issue",
        return_value={"id": "l1", "identifier": "ENG-7", "url": "https://linear/x"},
    ), patch(
        "company_brain.agents.operations.slack.slack_action_items.task_class_fan_out",
        return_value=["linear", "slack"],
    ), patch(
        "company_brain.agents.operations.slack.slack_action_items.slack_client.permalink",
        return_value="https://slack/x",
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
        "company_brain.agents.engineering.linear.linear_completed.slack_thread_respond.slack_client.post_thread_reply",
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

    with patch(
        "company_brain.agents.engineering.linear.linear_completed.dispatcher.task_class_fan_out",
        return_value=["linear", "slack"],
    ), patch(
        "company_brain.agents.engineering.linear.linear_completed.slack_thread_respond.SlackThreadRespondAgent"
    ) as mock_cls:
        mock_cls.return_value.run.return_value = {"status": "replied"}
        result = agent.run(task_id="t1", linear_issue={"state": {"name": "Done"}})

    assert result["platforms"]["slack"]["status"] == "replied"


def test_thread_watcher_dispatches_on_action_item():
    agent = SlackThreadWatcherAgent(MagicMock())
    msg = {"ts": "1.1", "text": "TODO: fix onboarding"}

    with patch(
        "company_brain.agents.operations.slack.slack_thread_watcher.cfg.watched_channels",
        return_value=["#team-ops"],
    ), patch.object(agent, "_since_timestamp", return_value=MagicMock()), patch(
        "company_brain.agents.operations.slack.slack_thread_watcher.slack_client.fetch_channel_messages",
        return_value=[msg],
    ), patch(
        "company_brain.agents.operations.slack.slack_thread_watcher.slack_client.datetime_to_slack_ts",
        return_value=0.0,
    ), patch(
        "company_brain.agents.operations.slack.slack_thread_watcher.is_handled",
        return_value=False,
    ), patch(
        "company_brain.agents.operations.slack.slack_thread_watcher.mark_handled",
    ), patch.object(
        agent,
        "_dispatch_action_items",
        return_value={"status": "created"},
    ) as mock_dispatch:
        scanned, hits = agent._scan_channel("#team-ops")

    assert scanned == 1
    assert hits == 1
    mock_dispatch.assert_called_once()
