"""Tests for Discord ingest triage, events router, and routing store."""

from unittest.mock import MagicMock, patch

from company_brain.agents.growth.discord.events_router import DiscordEventsRouter
from company_brain.agents.growth.discord.ingest_triage import IngestTriageAgent
from company_brain.agents.growth.discord.routing import DiscordRoutingStore
from company_brain.agents.growth.discord.triage_heuristics import (
    classify_tier0,
    is_spam,
)


def test_classify_tier0_bug():
    result = classify_tier0(
        {"content": "app crash on startup", "author": {"id": "1"}, "type": 0},
        channel_id="100",
    )
    assert result.urgency == "immediate"
    assert result.kind == "bug_pending"
    assert result.category == "bug"


def test_classify_tier0_feature():
    result = classify_tier0(
        {"content": "feature request: add export to CSV", "author": {"id": "1"}, "type": 0},
        channel_id="100",
    )
    assert result.kind == "feature_pending"
    assert result.category == "feature"


def test_classify_tier0_skip_bot():
    result = classify_tier0(
        {"content": "hello", "author": {"id": "1", "bot": True}, "type": 0},
        channel_id="100",
    )
    assert result.urgency == "skip"
    assert result.reason == "bot_message"


def test_classify_tier0_skip_spam():
    assert is_spam("free nitro click here")
    result = classify_tier0(
        {"content": "free nitro click here", "author": {"id": "1"}, "type": 0},
        channel_id="100",
    )
    assert result.urgency == "skip"


def test_classify_tier0_technical_question():
    result = classify_tier0(
        {"content": "How do I configure the wiki sync?", "author": {"id": "1"}, "type": 0},
        channel_id="100",
    )
    assert result.urgency == "deferred"
    assert result.kind == "technical_pending"


def test_classify_tier0_excluded_channel(tmp_path, monkeypatch):
    from company_brain.agents.growth.discord import channels_config

    registry = tmp_path / "discord_channels.json"
    registry.write_text(
        '{"version":1,"channels":{"200":{"name":"off-topic","ingest_mode":"out_of_scope"}}}'
    )
    monkeypatch.setattr(channels_config, "CHANNELS_FILE", registry)
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.channels_config.cfg.exclude_channels",
        lambda: [],
    )

    result = classify_tier0(
        {"content": "hello world", "author": {"id": "1"}, "type": 0},
        channel_id="200",
    )
    assert result.urgency == "skip"


def test_ingest_triage_writes_routing_record(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    registry = tmp_path / "discord_channels.json"
    registry.write_text('{"version":1,"guild_id":"","channels":{}}')
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.routing.resolve_wiki_dir",
        lambda: wiki,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.channels_config.CHANNELS_FILE",
        registry,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.ingest_triage.cfg.guild_id",
        lambda: "GUILD1",
    )
    with patch(
        "company_brain.agents.growth.discord.ingest_triage.discord_client.bot_user_id",
        return_value="BOT1",
    ):
        agent = IngestTriageAgent(MagicMock())
        result = agent.process_message(
            "100",
            {
                "content": "feature request: dark mode",
                "author": {"id": "U1", "username": "dev1"},
                "id": "9001",
                "channel_id": "100",
                "type": 0,
            },
        )
    assert result["status"] == "routed"
    assert result["kind"] == "feature_pending"
    store = DiscordRoutingStore(wiki_dir=wiki)
    record = store.read("100", "9001")
    assert record is not None
    assert record.community is True
    assert record.extracted.get("author_handle") == "dev1"


def test_events_router_message_create(monkeypatch):
    router = DiscordEventsRouter(MagicMock())
    with patch.object(
        IngestTriageAgent,
        "process_message",
        return_value={"status": "routed"},
    ) as mock_process:
        result = router.handle_dispatch(
            "MESSAGE_CREATE",
            {
                "channel_id": "100",
                "content": "bug: login broken",
                "author": {"id": "1", "username": "dev"},
                "id": "55",
                "type": 0,
            },
        )
    assert result["status"] == "routed"
    mock_process.assert_called_once()


def test_events_router_ignores_unknown():
    router = DiscordEventsRouter(MagicMock())
    result = router.handle_dispatch("PRESENCE_UPDATE", {})
    assert result["status"] == "ignored"
