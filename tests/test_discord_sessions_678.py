"""Tests for Discord sessions 6–8: absorb, member scoring, manager, onboarding."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from company_brain.agents.growth.discord.discord_onboarding import (
    DiscordOnboardingAgent,
    estimate_backfill,
)
from company_brain.agents.growth.discord.member_scoring import MemberScoringAgent, _member_slug
from company_brain.agents.growth.discord.routing import DiscordRoutingRecord, DiscordRoutingStore
from company_brain.agents.growth.discord.technical_absorb import TechnicalAbsorbAgent
from company_brain.agents.growth.discord_manager import DiscordManager


def test_member_slug_sanitizes_handle():
    assert _member_slug("Nick#1234") == "nick-1234"


def test_technical_absorb_enqueues_raw_entry(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    raw = tmp_path / "raw"
    wiki.mkdir()
    (raw / "entries").mkdir(parents=True)
    registry = tmp_path / "discord_channels.json"
    registry.write_text('{"version":1,"guild_id":"","channels":{"100":{"name":"general"}}}')

    monkeypatch.setattr(
        "company_brain.agents.growth.discord.routing.resolve_wiki_dir",
        lambda: wiki,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.technical_absorb.resolve_raw_dir",
        lambda: raw,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.technical_absorb.channels_config.CHANNELS_FILE",
        registry,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.technical_absorb.discord_client.discord_is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.technical_absorb.discord_client.fetch_conversation_messages",
        lambda *_a, **_k: [
            {
                "content": " ".join(["how do I configure the wiki sync?"] * 8),
                "author": {"id": "1", "username": "dev"},
            }
        ],
    )

    store = DiscordRoutingStore(wiki_dir=wiki)
    now = datetime.now(timezone.utc).isoformat()
    store.write(
        DiscordRoutingRecord(
            channel_id="100",
            thread_id="t1",
            parent_channel_id="100",
            created_at=now,
            updated_at=now,
            kind="discussion_open",
            community=True,
            handled={"community_intake": now},
            extracted={
                "author_id": "1",
                "author_handle": "dev",
                "text_preview": "how do I configure the wiki sync?",
                "category": "technical",
            },
        )
    )

    with patch(
        "company_brain.agents.growth.discord.technical_absorb.cfg.absorb_batch_hour_utc",
        return_value=0,
    ):
        result = TechnicalAbsorbAgent(MagicMock()).run()

    assert result["enqueued"] == 1
    entries = list((raw / "entries").glob("*.md"))
    assert len(entries) == 1
    record = store.read("100", "t1")
    assert record is not None
    assert record.handled.get("technical_absorb")
    assert record.extracted.get("raw_entry_id")


def test_member_scoring_writes_profile(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.routing.resolve_wiki_dir",
        lambda: wiki,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.member_scoring.discord_client.discord_is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.member_scoring.cfg.member_scoring_min_messages",
        lambda: 2,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.member_scoring.cfg.interesting_score_threshold",
        lambda: 4,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.member_scoring.write_wiki_page",
        lambda *a, **k: "page-id",
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.member_scoring.growth_notifier",
        lambda: MagicMock(emit=MagicMock(return_value=True)),
    )

    store = DiscordRoutingStore(wiki_dir=wiki)
    now = datetime.now(timezone.utc).isoformat()
    for idx in range(3):
        store.write(
            DiscordRoutingRecord(
                channel_id="100",
                thread_id=f"t{idx}",
                parent_channel_id="100",
                created_at=now,
                updated_at=now,
                kind="technical_pending",
                community=True,
                extracted={
                    "author_id": "U1",
                    "author_handle": "poweruser",
                    "text_preview": f"great question about deployment {idx}",
                },
            )
        )

    agent = MemberScoringAgent(MagicMock())
    agent._score_member = MagicMock(  # type: ignore[method-assign]
        return_value=(5, "Asks deep technical questions.", "Self-hosting company-brain.")
    )
    agent._should_notify = MagicMock(return_value=True)  # type: ignore[method-assign]
    result = agent.run()
    assert result["scored"] == 1
    assert result["notified"] == 1
    agent._score_member.assert_called_once()


def test_discord_manager_monthly_gate(monkeypatch):
    manager = DiscordManager(MagicMock())
    monkeypatch.setattr(manager._state, "get", lambda key: "2026-07" if "month" in key else None)
    assert manager._should_run_member_scoring() is False
    monkeypatch.setattr(manager._state, "get", lambda key: None)
    assert manager._should_run_member_scoring() is True


def test_discord_manager_does_not_complete_failed_dispatch():
    manager = DiscordManager(MagicMock())
    runtime = MagicMock()
    runtime.run.side_effect = RuntimeError("unavailable")

    assert manager._run_agent(runtime, MemberScoringAgent) is False


def test_onboarding_estimate_not_configured(monkeypatch):
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.discord_onboarding.discord_client.discord_is_configured",
        lambda: False,
    )
    assert estimate_backfill()["status"] == "not_configured"


def test_onboarding_backfill_routes_messages(tmp_path, monkeypatch):
    registry = tmp_path / "discord_channels.json"
    registry.write_text(
        '{"version":1,"guild_id":"","channels":{"100":{"name":"general","type":0}}}'
    )
    wiki = tmp_path / "wiki"
    wiki.mkdir()

    monkeypatch.setattr(
        "company_brain.agents.growth.discord.discord_onboarding.discord_client.discord_is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.discord_onboarding.cfg.guild_id",
        lambda: "",
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.discord_onboarding.channels_config.CHANNELS_FILE",
        registry,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.ingest_triage.channels_config.CHANNELS_FILE",
        registry,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.routing.resolve_wiki_dir",
        lambda: wiki,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.discord_onboarding.discord_client.fetch_channel_messages",
        lambda *_a, **_k: [
            {
                "content": "feature request: export",
                "author": {"id": "1", "username": "dev"},
                "id": "55",
                "channel_id": "100",
                "type": 0,
            }
        ],
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.ingest_triage.discord_client.bot_user_id",
        lambda: "BOT",
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.community_intake.maybe_dispatch_community_intake",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.discord_onboarding.CommunityIntakeAgent.run",
        lambda self: {"processed": 0},
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.discord_onboarding.OpenConversationAgent.run",
        lambda self: {"open_count": 0},
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.discord_onboarding.DiscordOnboardingAgent._start_manager",
        lambda self: None,
    )

    result = DiscordOnboardingAgent(MagicMock()).run(start_manager=False, backfill_days=7)
    assert result["status"] == "ok"
    assert result["backfill"]["routed"] == 1
