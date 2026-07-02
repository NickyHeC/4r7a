"""Unit tests for Phase-4 duplicate detection and Linear config."""

from company_brain.agents.operations.gmail.duplicate_across_mailboxes import _fingerprint
from company_brain.agents.operations.shared.routing import RoutingRecord


def test_fingerprint_stable():
    a = RoutingRecord(
        message_id="1",
        thread_id="t",
        mailbox="me",
        triaged_at="",
        extracted={"subject": "Hello", "from": "a@b.com"},
    )
    b = RoutingRecord(
        message_id="2",
        thread_id="t2",
        mailbox="me",
        triaged_at="",
        extracted={"subject": "Hello", "from": "a@b.com"},
    )
    assert _fingerprint(a) == _fingerprint(b)


def test_linear_configured_with_env(monkeypatch):
    from company_brain.agents.engineering.linear import linear_client

    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    monkeypatch.delenv("LINEAR_OAUTH_ACCESS_TOKEN", raising=False)
    assert linear_client.linear_is_configured() is False
    monkeypatch.setenv("LINEAR_API_KEY", "lin_test_abc")
    assert linear_client.linear_is_configured() is True
