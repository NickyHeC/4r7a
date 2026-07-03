"""Tests for inbound scoring heuristics."""

from company_brain.agents.operations.shared.inbound_score import (
    score_inbound,
    should_slack_alert,
)
from company_brain.crm.registry import RegistryEntry


def test_reputable_domain_boosts_score(monkeypatch):
    monkeypatch.setattr(
        "company_brain.agents.operations.shared.inbound_score.reputable_domains",
        lambda: {"techcrunch.com"},
    )
    result = score_inbound(
        "press-podcast",
        subject="Interview request",
        from_hdr="Editor <news@techcrunch.com>",
        body="We would love to have you on our podcast.",
    )
    assert result.score >= 6
    assert any(r.startswith("reputable_domain:") for r in result.reasons)


def test_free_email_penalty():
    result = score_inbound(
        "press-podcast",
        subject="Quick question",
        from_hdr="Sam <sam@gmail.com>",
        body="Reaching out about your product.",
    )
    assert any(r.startswith("free_email:") for r in result.reasons)
    assert any(r.startswith("generic:") for r in result.reasons)


def test_known_connection_boost():
    entry = RegistryEntry(slug="jane-acme-com", segment="connection", source="contact")
    result = score_inbound(
        "event-invitation",
        subject="Summit invite",
        from_hdr="Jane <jane@acme.com>",
        body="Join us at our annual summit.",
        registry_entry=entry,
    )
    assert any(r.startswith("known_connection") for r in result.reasons)


def test_should_slack_alert_threshold(monkeypatch):
    monkeypatch.setattr(
        "company_brain.crm.config.slack_score_threshold",
        lambda: 6,
    )
    high = score_inbound(
        "press-podcast",
        subject="Podcast interview",
        from_hdr="Show <host@majorpress.com>",
        body="podcast interview media",
    )
    while high.score < 6:
        high.score += 1
    assert should_slack_alert("press-podcast", high)
    assert not should_slack_alert("partnership", high)
