"""Granola onboarding agent tests."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from company_brain.agents.operations.granola.granola_onboarding import GranolaOnboardingAgent

_ONBOARD = "company_brain.agents.operations.granola.granola_onboarding"


@patch("company_brain.runtime.get_runtime")
@patch(f"{_ONBOARD}.granola_is_configured", return_value=True)
@patch(f"{_ONBOARD}.backfill_days", return_value=3)
@patch(f"{_ONBOARD}.IngestAgent")
def test_onboarding_backfills_and_starts_watch(
    mock_ingest_cls,
    _backfill_days,
    _configured,
    mock_get_runtime,
):
    runtime = MagicMock()
    runtime.run.side_effect = [
        {"status": "ok", "notes": 2},
        {"status": "empty", "notes": 0},
        {"status": "already_handled", "notes": 0},
    ]
    mock_get_runtime.return_value = runtime

    agent = GranolaOnboardingAgent(MagicMock())
    result = agent.run(start_manager=True, backfill_days_override=3)

    assert result["status"] == "ok"
    assert result["total_notes"] == 2
    assert runtime.run.call_count == 3
    called_days = [call.kwargs["target_date"] for call in runtime.run.call_args_list]
    today = date.today()
    assert called_days[0] == today.fromordinal(today.toordinal() - 2)
    assert called_days[-1] == today
    runtime.start.assert_called_once()
    from company_brain.agents.operations.granola.meeting_watch import (
        MeetingWatchAgent,
    )

    assert runtime.start.call_args[0][0] is MeetingWatchAgent


@patch(f"{_ONBOARD}.granola_is_configured", return_value=False)
def test_onboarding_skips_when_not_configured(_configured):
    agent = GranolaOnboardingAgent(MagicMock())
    result = agent.run()
    assert result["status"] == "not_configured"


@patch("company_brain.runtime.get_runtime")
@patch(f"{_ONBOARD}.granola_is_configured", return_value=True)
@patch(f"{_ONBOARD}.IngestAgent")
def test_onboarding_can_skip_manager_start(mock_ingest_cls, _configured, mock_get_runtime):
    runtime = MagicMock()
    runtime.run.return_value = {"status": "empty", "notes": 0}
    mock_get_runtime.return_value = runtime

    agent = GranolaOnboardingAgent(MagicMock())
    agent.run(start_manager=False, backfill_days_override=1)

    runtime.run.assert_called_once()
    runtime.start.assert_not_called()
