"""Unit tests for Phase-1 Gmail triage classifiers."""

from pathlib import Path

import pytest
import yaml

from company_brain.agents.operations.shared.classify import classify_message


def _msg(*, subject: str = "", from_: str = "", snippet: str = "", list_unsub: str = ""):
    headers = [
        {"name": "Subject", "value": subject},
        {"name": "From", "value": from_},
    ]
    if list_unsub:
        headers.append({"name": "List-Unsubscribe", "value": list_unsub})
    return {"payload": {"headers": headers}, "snippet": snippet}


def _load_eval_cases():
    path = Path(__file__).parent / "fixtures" / "gmail_classify_cases.yaml"
    data = yaml.safe_load(path.read_text())
    return data["cases"]


def test_receipt_mark_read_not_archived_immediately():
    result = classify_message(_msg(subject="Your receipt from Stripe"))
    assert "Receipts" in result.domain_tags
    assert result.mark_read is True
    assert result.archive_now is False


def test_newsletter_mark_read():
    result = classify_message(
        _msg(subject="Weekly digest", from_="Substack <news@substack.com>", list_unsub="<mailto:unsub@x.com>")
    )
    assert any(t.startswith("Newsletters/") for t in result.domain_tags)
    assert result.mark_read is True


def test_cold_sales_auto_archive():
    result = classify_message(_msg(subject="Quick question about your product", from_="sales@vendor.com"))
    assert "Cold Inbound/Sales Outreach" in result.domain_tags
    assert result.archive_now is True


def test_ai_meeting_notes():
    result = classify_message(_msg(subject="Meeting notes", from_="Granola <notes@granola.so>"))
    assert "AI Meeting Notes" in result.domain_tags
    assert result.archive_now is True


def test_employee_profile_flat_newsletter(monkeypatch):
    monkeypatch.setenv("GMAIL_PROFILE", "employee")
    result = classify_message(
        _msg(subject="Weekly digest", from_="Substack <news@substack.com>", list_unsub="<mailto:unsub@x.com>")
    )
    assert result.domain_tags == ["Newsletters"]
    assert result.mark_read is True


def test_employee_profile_flat_cold_inbound(monkeypatch):
    monkeypatch.setenv("GMAIL_PROFILE", "employee")
    result = classify_message(_msg(subject="Quick question about your product", from_="sales@vendor.com"))
    assert result.domain_tags == ["Cold Inbound"]
    assert result.archive_now is True


@pytest.mark.parametrize("case", _load_eval_cases(), ids=lambda c: c["name"])
def test_classifier_eval_cases(case):
    msg = _msg(
        subject=case["message"].get("subject", ""),
        from_=case["message"].get("from", ""),
        snippet=case["message"].get("snippet", ""),
        list_unsub=case["message"].get("list_unsub", ""),
    )
    result = classify_message(msg)
    if "expect_domain" in case:
        for tag in case["expect_domain"]:
            assert tag in result.domain_tags
    if "expect_domain_prefix" in case:
        assert any(t.startswith(case["expect_domain_prefix"]) for t in result.domain_tags)
    if "expect_attention" in case:
        assert result.attention == case["expect_attention"]
    if case.get("mark_read"):
        assert result.mark_read is True
    if case.get("archive_now"):
        assert result.archive_now is True
