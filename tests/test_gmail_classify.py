"""Unit tests for Phase-1 Gmail triage classifiers."""

from company_brain.agents.operations.shared.classify import classify_message


def _msg(*, subject: str = "", from_: str = "", snippet: str = "", list_unsub: str = ""):
    headers = [
        {"name": "Subject", "value": subject},
        {"name": "From", "value": from_},
    ]
    if list_unsub:
        headers.append({"name": "List-Unsubscribe", "value": list_unsub})
    return {"payload": {"headers": headers}, "snippet": snippet}


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
