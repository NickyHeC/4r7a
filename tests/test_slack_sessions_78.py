"""Tests for Slack sessions 7–8: Weave, onboarding, HR."""

from unittest.mock import MagicMock

from company_brain.agents.admin.change_request import classify_change_class
from company_brain.agents.admin.weave_auth import can_invoke_weave, resolve_weave_requester
from company_brain.agents.admin.weave_triage import WeaveTriageAgent
from company_brain.agents.hr.employee_offboarding import EmployeeOffboardingAgent
from company_brain.agents.operations.slack.offboard_signal import _is_deactivation
from company_brain.agents.operations.slack.slack_onboarding import estimate_backfill
from company_brain.agents.operations.slack.weave_events_router import WeaveEventsRouter
from company_brain.members_config import MemberBindings, MembersConfig, MemberSpec
from company_brain.roster_config import RosterConfig, RosterPerson, promote_roster_to_member


def test_classify_change_class_config_only():
    assert classify_change_class("Please update members.yaml roster") == "config_only"


def test_classify_change_class_security():
    assert classify_change_class("Fix auth token leak in bridge") == "security_ingest"


def test_roster_cannot_invoke_weave(monkeypatch):
    roster = RosterConfig(
        people={"jane": RosterPerson(email="j@co.com", slack_user_id="UROSTER")}
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.weave_auth.load_roster_config",
        lambda: roster,
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.weave_auth.load_members_config",
        lambda: MembersConfig(members={}),
    )
    requester = resolve_weave_requester("UROSTER")
    allowed, reason = can_invoke_weave(requester)
    assert not allowed
    assert reason == "roster_not_allowed"


def test_member_can_invoke_weave(monkeypatch):
    members = MembersConfig(
        members={
            "alice": MemberSpec(
                email="a@co.com",
                bindings=MemberBindings(slack_user_id="UALICE"),
            )
        }
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.weave_auth.load_roster_config",
        lambda: RosterConfig(people={}),
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.weave_auth.load_members_config",
        lambda: members,
    )
    requester = resolve_weave_requester("UALICE")
    allowed, reason = can_invoke_weave(requester)
    assert allowed
    assert reason == "ok"


def test_weave_triage_rejects_roster(monkeypatch):
    from company_brain.agents.admin.weave_auth import WeaveRequester

    monkeypatch.setattr(
        "company_brain.agents.admin.weave_triage.resolve_weave_requester",
        lambda _uid: WeaveRequester(slack_user_id="U1", roster_key="jane", is_w2=False),
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.weave_triage.can_invoke_weave",
        lambda _r: (False, "roster_not_allowed"),
    )
    agent = WeaveTriageAgent(MagicMock())
    out = agent.run(slack_user_id="U1", text="update config")
    assert out["status"] == "rejected"


def test_weave_events_router_mention(monkeypatch):
    monkeypatch.setattr(
        "company_brain.runtime.get_runtime",
        lambda: MagicMock(run=MagicMock(return_value={"status": "submitted", "request_id": "abc"})),
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.weave_events_router.slack_client.permalink",
        lambda *_a, **_k: "",
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.weave_events_router.slack_client.post_thread_reply",
        lambda *_a, **_k: "ts",
    )
    router = WeaveEventsRouter(MagicMock())
    out = router.handle_payload(
        {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "channel": "C1",
                "ts": "1.0",
                "user": "U1",
                "text": "<@UBOT> update members.yaml",
            },
        }
    )
    assert out["status"] == "weave_triage"


def test_promote_roster_to_member(tmp_path, monkeypatch):
    roster_path = tmp_path / "roster.yaml"
    members_path = tmp_path / "members.yaml"
    roster_path.write_text(
        "people:\n  jane:\n    email: jane@co.com\n    slack_user_id: U1\n"
    )
    members_path.write_text("members: {}\n")
    monkeypatch.setattr("company_brain.roster_config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("company_brain.roster_config.ROSTER_FILE", roster_path)
    monkeypatch.setattr("company_brain.members_config.CONFIG_DIR", tmp_path)

    key = promote_roster_to_member("jane", role="member")
    assert key == "jane"
    assert "jane:" in members_path.read_text()
    assert "jane:" not in roster_path.read_text()


def test_offboard_proposal(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setattr(
        "company_brain.config.resolve_wiki_dir",
        lambda: wiki,
    )
    monkeypatch.setattr(
        "company_brain.agents.hr.employee_offboarding.append_hiring_log",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "company_brain.agents.hr.employee_offboarding.EmployeeOffboardingAgent._notify_admin",
        lambda *a, **k: None,
    )
    members = MembersConfig(
        members={
            "bob": MemberSpec(
                email="bob@co.com",
                bindings=MemberBindings(slack_user_id="UBOB"),
            )
        }
    )
    monkeypatch.setattr(
        "company_brain.agents.hr.employee_offboarding.load_members_config",
        lambda: members,
    )
    result = EmployeeOffboardingAgent(MagicMock()).run(member_key="bob")
    assert result["status"] == "proposed"
    assert result["wiki_path"] == "hr/offboard-proposal/bob.md"


def test_is_deactivation_user_change():
    event = {"type": "user_change", "user": {"id": "U9", "deleted": True}}
    assert _is_deactivation(event)


def test_estimate_backfill_not_configured(monkeypatch):
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.slack_onboarding.slack_client.slack_is_configured",
        lambda: False,
    )
    assert estimate_backfill()["status"] == "not_configured"
