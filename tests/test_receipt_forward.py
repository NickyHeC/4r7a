"""Receipt forwarding tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from company_brain.agents.operations.gmail.receipt_forward import (
    _eligible_sources,
    forward_missing_receipts,
)
from company_brain.agents.operations.shared.routing import RoutingRecord

_FWD = "company_brain.agents.operations.gmail.receipt_forward"


@patch("company_brain.agents.operations.gmail.receipt_forward.rest.mailbox_on_company_domain")
@patch("company_brain.agents.operations.gmail.receipt_forward.connected_mailboxes")
def test_eligible_sources_filters_destination_and_external(mock_boxes, mock_on_domain):
    mock_boxes.return_value = ["me", "billing@company.com", "personal@gmail.com"]
    mock_on_domain.side_effect = lambda mb, domain: mb != "personal@gmail.com"
    sources = _eligible_sources("me", "company.com")
    assert sources == ["billing@company.com"]


@patch(f"{_FWD}.mark_handled")
@patch(f"{_FWD}.is_handled", return_value=False)
@patch(f"{_FWD}.rest.copy_message_to_mailbox")
@patch(f"{_FWD}._eligible_sources", return_value=["billing@company.com"])
@patch(f"{_FWD}.receipt_forward_enabled", return_value=True)
@patch(f"{_FWD}.receipt_company_domain", return_value="company.com")
@patch(f"{_FWD}.receipt_destination_mailbox", return_value="me")
def test_forward_missing_receipts_copies(
    _dest,
    _domain,
    _enabled,
    _sources,
    mock_copy,
    _is_handled,
    _mark,
):
    store = MagicMock()
    record = RoutingRecord(
        message_id="m1",
        thread_id="t1",
        mailbox="billing@company.com",
        triaged_at=datetime.now(timezone.utc).isoformat(),
        domain_tags=["Receipts"],
        extracted={"from": "Stripe <billing@stripe.com>"},
    )
    store.iter_mailbox.return_value = [record]
    since = datetime.now(timezone.utc) - timedelta(hours=1)

    result = forward_missing_receipts(
        since=since,
        missing_domains={"stripe.com"},
        store=store,
    )

    assert result["forwarded"] == 1
    mock_copy.assert_called_once()
    store.write.assert_called_once()


@patch(f"{_FWD}.receipt_forward_enabled", return_value=False)
def test_forward_disabled(_enabled):
    result = forward_missing_receipts(
        since=datetime.now(timezone.utc),
        missing_domains={"stripe.com"},
    )
    assert result["status"] == "disabled"


@patch("company_brain.agents.operations.gmail.gmail_rest.get_profile")
def test_mailbox_on_company_domain(mock_profile):
    from company_brain.agents.operations.gmail import gmail_rest as rest

    mock_profile.return_value = {"emailAddress": "ceo@company.com"}
    assert rest.mailbox_on_company_domain("me", "company.com") is True
    assert rest.mailbox_on_company_domain("billing@company.com", "company.com") is True
    assert rest.mailbox_on_company_domain("billing@other.com", "company.com") is False
