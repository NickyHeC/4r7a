"""Tests for Slack sessions 4–6: customer support, ask_wiki, issue sync."""

from unittest.mock import MagicMock

from company_brain.agents.engineering.github.issue_sync import _issue_slug
from company_brain.agents.operations.customer_support import (
    CustomerIntake,
    CustomerSupportOrchestrator,
    classify_customer_intake,
    rebuild_feature_request_ranked,
)
from company_brain.agents.operations.slack.events_router import SlackEventsRouter
from company_brain.agents.operations.slack.internal_meeting_scheduler import is_meeting_request
from company_brain.agents.operations.slack.rate_limits import (
    RateLimitExceeded,
    check_wiki_query_limit,
)
from company_brain.agents.operations.slack.wiki_acl import (
    ask_wiki_allowed,
    path_allowed,
    search_wiki_snippets,
)
from company_brain.agents.operations.slack.wiki_commands import handle_wiki_command
from company_brain.members_config import MemberBindings, MembersConfig, MemberSpec


def test_classify_customer_intake_bug():
    intake = CustomerIntake(source="slack", title="Login broken", body="App crashes on login")
    assert classify_customer_intake(intake) == "bug"


def test_classify_customer_intake_feature():
    intake = CustomerIntake(
        source="gmail",
        title="Feature request",
        body="Could you add export to CSV?",
    )
    assert classify_customer_intake(intake) == "feature"


def test_classify_customer_intake_discussion_default():
    intake = CustomerIntake(source="slack", title="Question", body="How does billing work?")
    assert classify_customer_intake(intake) == "discussion"


def test_rebuild_feature_request_ranked_empty():
    body = rebuild_feature_request_ranked()
    assert "Feature Requests" in body
    assert "No feature requests" in body


def test_customer_support_orchestrator_discussion(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.routing.resolve_wiki_dir",
        lambda: wiki,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.customer_support.customer_support_notifier",
        lambda: MagicMock(emit=MagicMock(return_value=True)),
    )
    intake = CustomerIntake(
        source="slack",
        title="Billing question",
        body="Can we change plan?",
        channel="#customer",
        thread_ts="1.0",
    )
    result = CustomerSupportOrchestrator().process(intake)
    assert result["category"] == "discussion"
    assert result["open_thread"] is True


def test_ask_wiki_allowed_denies_connect(monkeypatch, tmp_path):
    from company_brain.agents.operations.slack import channels_config

    registry = tmp_path / "slack_channels.json"
    registry.write_text(
        '{"version":1,"channels":{"C_CONNECT":{"is_connect":true,"ask_wiki_allowed":false}}}'
    )
    monkeypatch.setattr(channels_config, "CHANNELS_FILE", registry)
    assert ask_wiki_allowed("C_CONNECT") is False


def test_path_allowed_prefix():
    assert path_allowed("engineering/github/open-pr.md", ["engineering/"])
    assert not path_allowed("admin/secret.md", ["engineering/"])


def test_rate_limit_admin_exempt(monkeypatch):
    members = MembersConfig(
        members={
            "alice": MemberSpec(
                email="alice@co.com",
                role="admin",
                bindings=MemberBindings(slack_user_id="UADMIN"),
            )
        }
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.rate_limits.load_members_config",
        lambda: members,
    )
    check_wiki_query_limit("UADMIN")


def test_rate_limit_enforced(monkeypatch):
    members = MembersConfig(
        members={
            "bob": MemberSpec(
                email="bob@co.com",
                bindings=MemberBindings(slack_user_id="UBOB"),
            )
        }
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.rate_limits.load_members_config",
        lambda: members,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.rate_limits.cfg.wiki_queries_per_user_hour",
        lambda: 1,
    )
    store: dict[str, int] = {}

    class FakeStore:
        def get(self, key):
            return store.get(key, 0)

        def set(self, key, val):
            store[key] = val

    monkeypatch.setattr(
        "company_brain.agents.operations.slack.rate_limits.StateStore",
        FakeStore,
    )
    check_wiki_query_limit("UBOB")
    try:
        check_wiki_query_limit("UBOB")
        raised = False
    except RateLimitExceeded:
        raised = True
    assert raised


def test_events_router_app_mention_help(monkeypatch):
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.wiki_commands.ask_wiki_allowed",
        lambda _cid: True,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.slack_client.post_thread_reply",
        lambda *_a, **_k: "ts",
    )
    router = SlackEventsRouter(MagicMock())
    out = router.handle_payload(
        {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "channel": "C1",
                "ts": "10.0",
                "user": "U1",
                "text": "<@UBOT> help",
            },
        }
    )
    assert out["status"] == "wiki_command"


def test_wiki_command_threads_no_member(monkeypatch):
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.wiki_commands.ask_wiki_allowed",
        lambda _cid: True,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.wiki_commands.load_members_config",
        lambda: MembersConfig(members={}),
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.slack_client.post_thread_reply",
        lambda *_a, **_k: "ts",
    )
    out = handle_wiki_command(
        channel_id="C1",
        thread_ts="1.0",
        command="threads",
        slack_user_id="U9",
    )
    assert out["status"] == "replied"


def test_is_meeting_request():
    assert is_meeting_request("Can we schedule a meeting next week?")
    assert not is_meeting_request("What is our refund policy?")


def test_issue_slug():
    assert _issue_slug(42, "Fix login bug") == "42-fix-login-bug"


def test_search_wiki_snippets_scoped(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    eng = wiki / "engineering"
    eng.mkdir(parents=True)
    (eng / "open-pr.md").write_text(
        "---\ntitle: Open PRs\nsync: location:engineering\n---\n\n# Open PRs\n\nPending reviews.\n"
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.wiki_acl.resolve_wiki_dir",
        lambda: wiki,
    )
    from company_brain.agents.operations.slack import channels_config

    registry = tmp_path / "slack_channels.json"
    registry.write_text(
        '{"version":1,"channels":{"C1":{"wiki_prefixes":["engineering/"],"ask_wiki_allowed":true}}}'
    )
    monkeypatch.setattr(channels_config, "CHANNELS_FILE", registry)
    hits = search_wiki_snippets("pending reviews", channel_id="C1")
    assert hits
    assert hits[0]["rel_path"] == "engineering/open-pr.md"
