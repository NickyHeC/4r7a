"""Tests for Discord community routing, feature dedup, and wiki snapshots."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from company_brain.agents.growth.discord.activity_snapshot import ActivitySnapshotAgent
from company_brain.agents.growth.discord.community_intake import CommunityIntakeAgent
from company_brain.agents.growth.discord.open_conversation import (
    OpenConversationAgent,
    render_open_conversations_body,
)
from company_brain.agents.growth.discord.product_catalog import (
    find_catalog_match,
    infer_product_slug,
    load_product_catalog,
)
from company_brain.agents.growth.discord.routing import DiscordRoutingRecord, DiscordRoutingStore
from company_brain.agents.operations.customer_support import (
    CommunityIntake,
    CustomerSupportOrchestrator,
    rebuild_feature_request_ranked,
)
from company_brain.members_config import MemberBindings, MembersConfig, MemberSpec


def _catalog_path(tmp_path, monkeypatch):
    catalog = tmp_path / "product_catalog.yaml"
    catalog.write_text(
        """
products:
  - slug: company-brain
    name: Company Brain
    status: available
    features:
      - "Markdown wiki with Notion mirror"
    in_build:
      - "Member bridge MCP"
  - slug: smol-machines
    name: Smol Machines
    status: available
    features:
      - "Smolfile VM spec"
    in_build: []
"""
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.product_catalog.REPO_CATALOG_PATH",
        catalog,
    )
    return catalog


def test_find_catalog_match_in_build(tmp_path, monkeypatch):
    _catalog_path(tmp_path, monkeypatch)
    catalog = load_product_catalog()
    match = find_catalog_match("Please add member bridge MCP support", catalog)
    assert match is not None
    assert match.match_kind == "in_build"
    assert match.product_slug == "company-brain"


def test_infer_product_slug_heuristic(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    _catalog_path(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.product_catalog.resolve_wiki_dir",
        lambda: wiki,
    )
    catalog = load_product_catalog()
    slug = infer_product_slug("Smol Machines question", "How do I use smolvm?", catalog)
    assert slug == "smol-machines"


def test_rebuild_feature_request_ranked_sections(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    (wiki / "product").mkdir(parents=True)
    _catalog_path(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.product_catalog.resolve_wiki_dir",
        lambda: wiki,
    )
    log = """# Feature Request Log

## 2026-07-11 12:00 UTC

**Title:** Dark mode
**Source:** discord
**Product:** company-brain

Please add dark mode.

## 2026-07-10 12:00 UTC

**Title:** Export CSV
**Source:** gmail

Could you add export?
"""
    (wiki / "product" / "feature-request-log.md").write_text(log)
    monkeypatch.setattr(
        "company_brain.wiki.publish.read_wiki_page",
        lambda path: log if path == "product/feature-request-log.md" else "",
    )
    body = rebuild_feature_request_ranked()
    assert "## Company Brain" in body
    assert "## General" in body
    assert "Dark mode" in body
    assert "Export CSV" in body


def test_community_intake_skips_crm(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    _catalog_path(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.routing.resolve_wiki_dir",
        lambda: wiki,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.product_catalog.resolve_wiki_dir",
        lambda: wiki,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.customer_support.record_interaction_on_contact",
        MagicMock(),
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.shared.growth_slack.growth_notifier",
        lambda: MagicMock(emit=MagicMock(return_value=True)),
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.customer_support.customer_support_notifier",
        lambda: MagicMock(emit=MagicMock(return_value=True)),
    )
    with patch(
        "company_brain.agents.operations.customer_support.linear_client.linear_is_configured",
        return_value=False,
    ):
        result = CustomerSupportOrchestrator().process_community(
            CommunityIntake(
                source="discord",
                title="Billing question",
                body="How does pricing work?",
                category="discussion",
                channel_id="100",
                thread_id="9001",
                parent_channel_id="100",
            )
        )
    assert result["category"] == "discussion"
    assert result["open_conversation"] is True
    store = DiscordRoutingStore(wiki_dir=wiki)
    record = store.read("100", "9001")
    assert record is not None
    assert record.kind == "discussion_open"


def test_feature_dedup_sends_discord_draft_not_log(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    (wiki / "product").mkdir(parents=True)
    _catalog_path(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.routing.resolve_wiki_dir",
        lambda: wiki,
    )
    draft_notifier = MagicMock(emit=MagicMock(return_value=True))
    growth_notifier = MagicMock(emit=MagicMock(return_value=True))
    monkeypatch.setattr(
        "company_brain.agents.growth.shared.growth_slack.discord_review_notifier",
        lambda: draft_notifier,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.shared.growth_slack.growth_notifier",
        lambda: growth_notifier,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.discord_client.conversation_author_ids",
        lambda *_a, **_k: set(),
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.product_catalog.draft_technical_reply",
        lambda **_: "Try the docs for Member bridge MCP.",
    )
    log_path = wiki / "product" / "feature-request-log.md"
    log_path.write_text("# Feature Request Log\n")

    result = CustomerSupportOrchestrator().process_community(
        CommunityIntake(
            source="discord",
            title="Member bridge",
            body="Please ship member bridge MCP",
            category="feature",
            channel_id="100",
            thread_id="9002",
            parent_channel_id="100",
        )
    )
    assert result.get("draft_sent") is True
    draft_notifier.emit.assert_called_once()
    growth_notifier.emit.assert_not_called()
    assert log_path.read_text().strip() == "# Feature Request Log"


def test_feature_dedup_skips_draft_when_team_member_replied(tmp_path, monkeypatch):
    _catalog_path(tmp_path, monkeypatch)
    draft_notifier = MagicMock(emit=MagicMock(return_value=True))
    monkeypatch.setattr(
        "company_brain.agents.growth.shared.growth_slack.discord_review_notifier",
        lambda: draft_notifier,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.discord_client.conversation_author_ids",
        lambda *_a, **_k: {"TEAM1"},
    )
    monkeypatch.setattr(
        "company_brain.members_config.load_members_config",
        lambda: MembersConfig(
            members={
                "nicky": MemberSpec(
                    bindings=MemberBindings(discord_id="TEAM1"),
                )
            }
        ),
    )
    result = CustomerSupportOrchestrator().process_community(
        CommunityIntake(
            source="discord",
            title="Member bridge",
            body="Please ship member bridge MCP",
            category="feature",
            channel_id="100",
            thread_id="9003",
            parent_channel_id="100",
        )
    )
    assert result.get("draft_skipped") is True
    draft_notifier.emit.assert_not_called()


def test_open_conversation_snapshot(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.routing.resolve_wiki_dir",
        lambda: wiki,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.open_conversation.load_members_config",
        lambda: MembersConfig(members={}),
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.open_conversation.discord_client.conversation_author_ids",
        lambda *_a, **_k: set(),
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
            extracted={
                "author_handle": "dev1",
                "text_preview": "How do I deploy?",
                "permalink": "https://discord.com/channels/g/100/1",
            },
        )
    )
    body = render_open_conversations_body(list(OpenConversationAgent(MagicMock())._open_records()))
    assert "dev1" in body
    assert "How do I deploy?" in body


def test_activity_snapshot_counts(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.routing.resolve_wiki_dir",
        lambda: wiki,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.activity_snapshot.write_wiki_page",
        lambda *a, **k: None,
    )
    store = DiscordRoutingStore(wiki_dir=wiki)
    recent = datetime.now(timezone.utc).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    for idx, ts in enumerate((recent, recent, old)):
        store.write(
            DiscordRoutingRecord(
                channel_id="100",
                thread_id=f"t{idx}",
                parent_channel_id="100",
                created_at=ts,
                updated_at=ts,
                kind="ingested",
                community=True,
                extracted={"author_id": f"u{idx}"},
            )
        )
    result = ActivitySnapshotAgent(MagicMock()).run()
    assert result["records_7d"] == 3
    assert result["records_30d"] == 3


def test_community_intake_agent_processes_pending(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    registry = tmp_path / "discord_channels.json"
    registry.write_text('{"version":1,"guild_id":"","channels":{"100":{"name":"general"}}}')
    _catalog_path(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.routing.resolve_wiki_dir",
        lambda: wiki,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.community_intake.channels_config.CHANNELS_FILE",
        registry,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.discord_client.discord_is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.discord.discord_client.fetch_conversation_messages",
        lambda *_a, **_k: [
            {"content": "feature request: widgets", "author": {"id": "1", "username": "dev"}}
        ],
    )
    monkeypatch.setattr(
        "company_brain.agents.growth.shared.growth_slack.growth_notifier",
        lambda: MagicMock(emit=MagicMock(return_value=True)),
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.customer_support.write_wiki_page",
        MagicMock(return_value="page"),
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.customer_support.rebuild_feature_request_ranked",
        lambda: "# Feature Requests\n",
    )
    store = DiscordRoutingStore(wiki_dir=wiki)
    now = datetime.now(timezone.utc).isoformat()
    store.write(
        DiscordRoutingRecord(
            channel_id="100",
            thread_id="t9",
            parent_channel_id="100",
            created_at=now,
            updated_at=now,
            kind="feature_pending",
            community=True,
            extracted={
                "text_preview": "feature request: widgets",
                "author_handle": "dev",
                "author_id": "1",
                "category": "feature",
            },
        )
    )
    result = CommunityIntakeAgent(MagicMock()).run()
    assert result["processed"] == 1
    record = store.read("100", "t9")
    assert record is not None
    assert record.handled.get("community_intake")
