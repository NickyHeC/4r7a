"""Granola client and ingest agent tests."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from company_brain.agents.operations.granola import granola_client as client
from company_brain.agents.operations.granola.ingest import (
    IngestAgent,
    format_digest_section,
    format_note_body,
)
from company_brain.agents.operations.shared import granola_config as cfg

SAMPLE_NOTE = {
    "id": "not_1d3tmYTlCICgjy",
    "title": "Quarterly review",
    "owner": {"name": "Alice", "email": "alice@company.com"},
    "attendees": [{"name": "Bob", "email": "bob@company.com"}],
    "calendar_event": {"title": "Q1 sync", "start_time": "2026-06-23T15:00:00Z"},
    "summary_markdown": "We reviewed the budget.",
    "transcript": [
        {"speaker": {"name": "Alice"}, "text": "Hello"},
        {"speaker": {"source": "speaker"}, "text": "Hi there"},
    ],
}


def test_format_note_body_includes_summary_and_transcript():
    body = format_note_body(SAMPLE_NOTE, member_label="alice")
    assert "Quarterly review" in body or "Alice" in body
    assert "## Summary" in body
    assert "We reviewed the budget." in body
    assert "## Transcript" in body
    assert "**Alice:** Hello" in body


def test_format_digest_section():
    section = format_digest_section(SAMPLE_NOTE, member_label="alice")
    assert section.startswith("## Quarterly review")
    assert "Member key: alice" in section
    assert "We reviewed the budget." in section


def test_list_notes_pagination(monkeypatch):
    responses = [
        {
            "notes": [{"id": "not_aaaaaaaaaaaaaa"}],
            "hasMore": True,
            "cursor": "page2",
        },
        {
            "notes": [{"id": "not_bbbbbbbbbbbbbb"}],
            "hasMore": False,
            "cursor": None,
        },
    ]

    def fake_request(method, url, **kwargs):
        payload = responses.pop(0)
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.json.return_value = payload
        return resp

    monkeypatch.setattr(client.requests, "request", fake_request)
    notes = client.list_notes("grn_test", created_after=date(2026, 6, 23))
    assert len(notes) == 2
    assert notes[0]["id"] == "not_aaaaaaaaaaaaaa"


def test_granola_mode_detection(monkeypatch):
    monkeypatch.delenv("GRANOLA_API_KEY", raising=False)
    monkeypatch.delenv("GRANOLA_MEMBER_KEYS", raising=False)
    monkeypatch.delenv("GRANOLA_MODE", raising=False)
    assert cfg.granola_mode() == "business"

    monkeypatch.setenv("GRANOLA_MODE", "enterprise")
    assert cfg.granola_mode() == "enterprise"

    monkeypatch.delenv("GRANOLA_MODE", raising=False)
    monkeypatch.setenv("GRANOLA_MEMBER_KEYS", "alice:grn_a,bob:grn_b")
    assert cfg.granola_mode() == "business"
    assert cfg.member_api_keys() == [
        ("alice", "", "grn_a"),
        ("bob", "", "grn_b"),
    ]


_INGEST = "company_brain.agents.operations.granola.ingest"


@patch(f"{_INGEST}.write_wiki_page")
@patch(f"{_INGEST}._persist_raw_entry")
@patch(f"{_INGEST}.client.list_notes_for_day")
@patch(f"{_INGEST}.client.get_note")
@patch(f"{_INGEST}.cfg.granola_mode", return_value="enterprise")
@patch(f"{_INGEST}.cfg.enterprise_api_key", return_value="grn_test")
@patch(f"{_INGEST}.cfg.granola_is_configured", return_value=True)
@patch(f"{_INGEST}.is_handled", return_value=False)
@patch(f"{_INGEST}.mark_handled")
def test_run_once_enterprise(
    mock_mark,
    mock_is_handled,
    _configured,
    _key,
    _mode,
    mock_get_note,
    mock_list,
    mock_persist,
    mock_write_wiki,
):
    mock_list.return_value = [{"id": SAMPLE_NOTE["id"]}]
    mock_get_note.return_value = SAMPLE_NOTE

    agent = IngestAgent(MagicMock())
    result = agent.run_once(target_date=date(2026, 6, 23))

    assert result["status"] == "ok"
    assert result["notes"] == 1
    mock_persist.assert_called_once()
    mock_write_wiki.assert_called_once()
    mock_mark.assert_called()


@patch(f"{_INGEST}.cfg.member_api_keys")
@patch(f"{_INGEST}.client.list_notes_for_day")
@patch(f"{_INGEST}.client.get_note")
@patch(f"{_INGEST}.cfg.granola_mode", return_value="business")
@patch(f"{_INGEST}.cfg.granola_is_configured", return_value=True)
@patch(f"{_INGEST}.is_handled", return_value=False)
@patch(f"{_INGEST}.mark_handled")
@patch(f"{_INGEST}.write_wiki_page")
@patch(f"{_INGEST}._persist_raw_entry")
def test_run_once_business_dedupes(
    mock_persist,
    mock_write,
    mock_mark,
    mock_is_handled,
    _configured,
    _mode,
    mock_get_note,
    mock_list,
    mock_member_keys,
):
    mock_member_keys.return_value = [
        ("alice", "alice@company.com", "grn_a"),
        ("bob", "bob@company.com", "grn_b"),
    ]
    mock_list.return_value = [{"id": SAMPLE_NOTE["id"]}]
    mock_get_note.return_value = SAMPLE_NOTE

    agent = IngestAgent(MagicMock())
    result = agent.run_once(target_date=date(2026, 6, 23))

    assert result["notes"] == 1
    assert mock_list.call_count == 2
    mock_persist.assert_called_once()


def test_run_once_does_not_mark_failed_empty_fetch(monkeypatch):
    mark = MagicMock()
    monkeypatch.setattr(cfg, "granola_is_configured", lambda: True)
    monkeypatch.setattr(cfg, "granola_mode", lambda: "enterprise")
    monkeypatch.setattr(cfg, "enterprise_api_key", lambda: "grn_test")
    monkeypatch.setattr(
        client,
        "list_notes_for_day",
        MagicMock(side_effect=client.GranolaAPIError("temporary failure")),
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.granola.ingest.is_handled",
        lambda *args: False,
    )
    monkeypatch.setattr("company_brain.agents.operations.granola.ingest.mark_handled", mark)

    result = IngestAgent(MagicMock()).run_once(target_date=date(2026, 6, 23))

    assert result["status"] == "retry"
    mark.assert_not_called()


def test_granola_api_error_status(monkeypatch):
    def fake_request(*args, **kwargs):
        resp = MagicMock()
        resp.ok = False
        resp.status_code = 401
        resp.text = "Invalid API key"
        return resp

    monkeypatch.setattr(client.requests, "request", fake_request)
    with pytest.raises(client.GranolaAPIError) as exc:
        client._request("GET", "/v1/notes", api_key="bad", params={})
    assert exc.value.status_code == 401
