"""Tests for Granola task extraction and meeting watch."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from company_brain.agents.operations.granola.granola_meeting_watch import (
    GranolaMeetingWatchAgent,
    _event_end,
)
from company_brain.agents.operations.granola.granola_task import extract_action_items


def test_extract_action_items_from_section():
    note = {
        "summary_markdown": (
            "## Summary\nDiscussed roadmap.\n\n"
            "## Action items\n"
            "- Alice will send the deck\n"
            "- Bob to follow up with vendor\n"
        ),
    }
    items = extract_action_items(note)
    assert len(items) >= 2
    assert any("Alice" in i for i in items)


def test_extract_action_items_keyword():
    note = {"summary": "TODO: update the wiki page with outcomes."}
    items = extract_action_items(note)
    assert any("wiki" in i.lower() for i in items)


def test_event_end_parsing():
    event = {"end": {"dateTime": "2026-06-26T15:00:00Z"}}
    end = _event_end(event)
    assert end is not None
    assert end.year == 2026


def test_meeting_watch_dispatches_ended_event():
    now = datetime.now(timezone.utc)
    end = now - timedelta(minutes=30)
    event = {
        "id": "evt1",
        "summary": "Team sync",
        "end": {"dateTime": end.isoformat().replace("+00:00", "Z")},
        "start": {"dateTime": (end - timedelta(hours=1)).isoformat().replace("+00:00", "Z")},
    }
    agent = GranolaMeetingWatchAgent(MagicMock())

    with patch(
        "company_brain.agents.operations.granola.granola_meeting_watch.cfg.granola_is_configured",
        return_value=True,
    ), patch.object(agent, "_ended_meetings", return_value=[event]), patch.object(
        agent, "_dispatch_ingest", return_value={"status": "ok"},
    ) as mock_ingest, patch.object(
        agent, "_maybe_miss_check", return_value=None,
    ), patch(
        "company_brain.agents.operations.granola.granola_meeting_watch.is_handled",
        return_value=False,
    ), patch(
        "company_brain.agents.operations.granola.granola_meeting_watch.mark_handled",
    ):
        result = agent.run_once()

    assert result["dispatched"] == 1
    mock_ingest.assert_called_once()
