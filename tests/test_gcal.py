"""Google Calendar availability and meeting scheduler tests."""

from __future__ import annotations

from datetime import date, datetime, time
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from company_brain.agents.operations.gcal.availability import find_available_slots
from company_brain.agents.operations.gmail.ext_meeting_scheduler import (
    _meeting_importance,
    _proposal_draft_body,
)


def test_meeting_importance_investor():
    record = MagicMock()
    record.contact_type = "investor"
    record.domain_tags = []
    assert _meeting_importance(record) == "high"


def test_meeting_importance_cold_inbound():
    record = MagicMock()
    record.contact_type = None
    record.domain_tags = ["Cold Inbound/Partnership"]
    assert _meeting_importance(record) == "low"


def test_proposal_draft_body_lists_slots():
    tz = ZoneInfo("UTC")
    from company_brain.agents.operations.gcal.availability import TimeSlot

    slots = [
        TimeSlot(
            start=datetime(2026, 6, 23, 10, 0, tzinfo=tz),
            end=datetime(2026, 6, 23, 10, 30, tzinfo=tz),
        )
    ]
    body = _proposal_draft_body(slots)
    assert "A few options" in body
    assert "Jun 23" in body


@patch("company_brain.agents.operations.gcal.availability.rest.free_busy")
@patch("company_brain.agents.operations.gcal.availability.rest.list_events")
@patch("company_brain.agents.operations.gcal.availability.business_hours")
@patch("company_brain.agents.operations.gcal.availability.timezone_name", return_value="UTC")
@patch("company_brain.agents.operations.gcal.availability.calendar_id", return_value="primary")
def test_find_available_slots_skips_busy(
    _cal_id,
    _tz,
    mock_bh,
    mock_list_events,
    mock_free_busy,
):
    mock_bh.return_value = (time(9, 0), time(12, 0))
    mock_list_events.return_value = []
    mock_free_busy.return_value = {
        "primary": [
            {
                "start": "2026-06-23T09:00:00Z",
                "end": "2026-06-23T10:00:00Z",
            }
        ]
    }
    slots = find_available_slots(
        duration_minutes=30,
        days_ahead=1,
        slot_count=2,
        start_day=date(2026, 6, 23),
    )
    assert slots
    assert slots[0].start.hour >= 10
