"""Tests for doctor scoring and deterministic checks."""

from __future__ import annotations

from company_brain.doctor.agents import run_agents_doctor
from company_brain.doctor.ops import run_ops_doctor
from company_brain.doctor.scoring import compute_score, new_fail_regressions
from company_brain.doctor.types import CheckResult, DoctorReport
from company_brain.doctor.naming import run_naming_doctor
from company_brain.doctor.wiki import run_wiki_doctor


def test_compute_score_no_issues() -> None:
    assert compute_score(set(), set()) == 100


def test_compute_score_fails_and_warns() -> None:
    assert compute_score({"a", "b"}, {"c"}) == 96  # 100 - 3 - 0.75 = 96.25 -> 96


def test_doctor_report_score_uses_unique_rules() -> None:
    report = DoctorReport(
        name="test",
        checks=[
            CheckResult("dup", "fail", "one"),
            CheckResult("dup", "fail", "two"),
            CheckResult("warn1", "warn", "w"),
        ],
    )
    assert report.score == 98  # 100 - 1.5 - 0.75


def test_new_fail_regressions() -> None:
    report = DoctorReport(
        name="agents",
        checks=[CheckResult("new_rule", "fail", "x")],
    )
    baseline = {"agents": {"old_rule"}}
    added = new_fail_regressions({"agents": report}, baseline)
    assert added["agents"] == {"new_rule"}


def test_wiki_doctor_no_notion_in_agents() -> None:
    report = run_wiki_doctor()
    notion = next(c for c in report.checks if c.check == "notion_direct_in_agents")
    assert notion.status == "pass"


def test_ops_doctor_slack_transport_only() -> None:
    report = run_ops_doctor()
    slack = next(c for c in report.checks if c.check == "slack_notifier_bypass")
    assert slack.status == "pass"


def test_agents_doctor_no_hyphen_filenames() -> None:
    report = run_agents_doctor()
    hyphens = next(c for c in report.checks if c.check == "agent_hyphen_filenames")
    assert hyphens.status == "pass"


def test_naming_doctor_passes() -> None:
    report = run_naming_doctor()
    assert report.score >= 85
    fails = [c for c in report.checks if c.status == "fail"]
    assert not fails, [c.check for c in fails]
