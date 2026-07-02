"""Unit tests for follow-up task heuristics."""

from company_brain.agents.engineering.linear.task_bindings import TaskBinding
from company_brain.agents.engineering.linear.task_standards import evaluate_follow_up


def test_follow_up_on_keyword():
    binding = TaskBinding(
        task_id="closed-1",
        origin={"platform": "gmail", "artifact_id": "m", "department": "operations"},
        linear={"issue_id": "l", "identifier": "ENG-1", "url": ""},
        status_track=[
            {
                "platform": "linear",
                "field": "status",
                "value": "Done",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "propagated_at": "2026-01-01T00:00:00+00:00",
                "source": "system:linear_completed",
            }
        ],
        title="Original subject",
    )
    activity = {"subject": "Re: Original", "body": "Need a follow-up please"}
    assert evaluate_follow_up(binding, activity) == "new_task"


def test_ignore_minor_reply():
    binding = TaskBinding(
        task_id="closed-2",
        origin={"platform": "gmail", "artifact_id": "m", "department": "operations"},
        linear={"issue_id": "l", "identifier": "ENG-2", "url": ""},
        status_track=[
            {
                "platform": "linear",
                "field": "status",
                "value": "Done",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "propagated_at": None,
                "source": "",
            }
        ],
        title="Thanks",
    )
    assert evaluate_follow_up(binding, {"subject": "Thanks", "body": "ok"}) == "ignore"
