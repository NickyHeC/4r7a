"""Tests for HR lifecycle v1 (onboard, LinkedIn parse, offboard, archive due)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import yaml

from company_brain.agents.hr.hr_manager import next_linkedin_run_at
from company_brain.agents.hr.linkedin.pull import PullAgent, _parse_sections
from company_brain.agents.hr.offboard_confirm import OffboardConfirmAgent
from company_brain.agents.hr.wiki_archive import WikiArchiveAgent, _is_due
from company_brain.config import load_config
from company_brain.members_config import load_members_config
from company_brain.roster_config import load_roster_config


def _hr_env(tmp_path: Path, monkeypatch):
    company = tmp_path / "wiki"
    employee = tmp_path / "employee_wiki"
    config_dir = tmp_path / "config"
    company.mkdir()
    employee.mkdir()
    config_dir.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(company))
    monkeypatch.setenv("COMPANY_BRAIN_EMPLOYEE_WIKI_DIR", str(employee))
    monkeypatch.setenv("COMPANY_BRAIN_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr("company_brain.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("company_brain.members_config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("company_brain.roster_config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("company_brain.agents.gates.CONFIG_DIR", config_dir)
    monkeypatch.setattr("company_brain.agents.hr.hr_config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("company_brain.bridge.config.CONFIG_DIR", config_dir)
    (config_dir / "members.yaml").write_text("members: {}\n")
    (config_dir / "roster.yaml").write_text("people: {}\n")
    (config_dir / "hr.yaml").write_text("archive_delay_days: 30\n")
    (config_dir / "bridge.yaml").write_text("tokens_path: bridge-tokens.json\n")
    return {"company": company, "employee": employee, "config": config_dir}


def test_parse_linkedin_sections() -> None:
    raw = """
## Bio
Alice builds payments infra.

## Posts
- 2026-07-01: shipped ledger
"""
    bio, posts = _parse_sections(raw)
    assert "Alice builds" in bio
    assert "shipped ledger" in posts
    bio2, posts2 = _parse_sections("## Bio\nx\n\n## Posts\n(none)\n")
    assert posts2 == ""
    assert "x" in bio2


def test_next_linkedin_run_at(monkeypatch) -> None:
    from company_brain.agents.hr import hr_config as cfg

    monkeypatch.setattr(cfg, "linkedin_run_day", lambda: 1)
    monkeypatch.setattr(cfg, "linkedin_run_hour", lambda: 9)
    monkeypatch.setattr(cfg, "linkedin_run_minute", lambda: 0)
    monkeypatch.setattr(cfg, "tz", lambda: ZoneInfo("America/Los_Angeles"))
    now = datetime(2026, 7, 22, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    nxt = next_linkedin_run_at(now)
    assert nxt == datetime(2026, 8, 1, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))


def test_archive_is_due() -> None:
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    assert _is_due(old) is True
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert _is_due(recent) is False
    assert _is_due("") is False


def test_hr_onboarding_seed(tmp_path, monkeypatch) -> None:
    env = _hr_env(tmp_path, monkeypatch)
    seed = {
        "current_employees": [
            {
                "key": "alice",
                "email": "alice@company.com",
                "employment_type": "w2",
                "department": "engineering",
                "linkedin_url": "https://www.linkedin.com/in/alice",
                "start_date": "2024-01-15",
                "role": "member",
            }
        ],
        "past_hires": [
            {
                "key": "bob",
                "email": "bob@example.com",
                "employment_type": "intern",
                "department": "product",
                "start_date": "2023-06-01",
                "end_date": "2023-09-01",
            }
        ],
    }
    (env["config"] / "hr_seed.yaml").write_text(yaml.safe_dump(seed))

    from company_brain.agents.hr.hr_onboarding import HrOnboardingAgent
    from company_brain.wiki.store import LocalWikiStore

    with (
        patch(
            "company_brain.agents.hr.hr_onboarding.HrOnboardingAgent._start_manager",
            return_value=[],
        ),
        patch(
            "company_brain.runtime.get_runtime",
        ) as rt,
    ):
        runtime = MagicMock()

        def _run(cls, config, **kwargs):
            if cls.__name__ == "EmployeeWikiOnboardingAgent":
                from company_brain.wiki.member_bootstrap import ensure_member_wiki

                ensure_member_wiki(
                    kwargs["member_key"],
                    email=kwargs.get("email", ""),
                    sync_notion=False,
                )
                return {"status": "ok", "member": kwargs["member_key"]}
            if cls.__name__ == "PullAgent":
                return {"status": "skipped", "reason": "mocked"}
            if cls.__name__ == "HiringLogAgent":
                return cls(config).run(**kwargs)
            return {"status": "ok"}

        runtime.run.side_effect = _run
        runtime.start.return_value = None
        rt.return_value = runtime

        result = HrOnboardingAgent(load_config()).run(
            seed=True,
            start_manager=False,
            pull_linkedin=True,
        )

    assert result["status"] == "ok"
    assert "alice" in result["onboarded"]
    assert "bob" in result["past_hires_logged"]
    members = load_members_config()
    assert members.get("alice") is not None
    assert members.get("alice").department == "engineering"
    assert members.get("alice").bindings.linkedin_url.endswith("/alice")
    wiki = LocalWikiStore(root=env["company"])
    assert wiki.exists("hr/hiring-log.md")
    log = wiki.read("hr/hiring-log.md").body
    assert "Joined — alice" in log or "alice" in log
    assert "Past hire — bob" in log or "bob" in log


def test_offboard_confirm_revokes_and_sets_departed(tmp_path, monkeypatch) -> None:
    env = _hr_env(tmp_path, monkeypatch)
    (env["config"] / "members.yaml").write_text(
        "members:\n"
        "  alice:\n"
        "    email: alice@company.com\n"
        "    status: active\n"
        "    department: engineering\n"
        "    bridge:\n"
        "      departments: [engineering]\n"
        "    bindings:\n"
        "      slack_user_id: U111\n"
        "      linkedin_url: https://www.linkedin.com/in/alice\n"
    )
    from company_brain.bridge.tokens import BridgeTokenStore

    store = BridgeTokenStore(config_dir=env["config"])
    plain = store.issue("alice")
    assert store.verify(plain) == "alice"

    with patch("company_brain.wiki.publish.write_wiki_page", return_value=None):
        result = OffboardConfirmAgent(load_config()).run(
            member_key="alice",
            reason="test",
        )
    assert result["status"] == "ok"
    assert result["bridge_revoked"] is True
    members = load_members_config()
    alice = members.get("alice")
    assert alice is not None
    assert alice.status == "departed"
    assert alice.departed_at
    assert alice.ingest.granola == "off"
    assert store.verify(plain) is None


def test_linkedin_pull_writes_bio_voice(tmp_path, monkeypatch) -> None:
    env = _hr_env(tmp_path, monkeypatch)
    (env["config"] / "members.yaml").write_text(
        "members:\n"
        "  alice:\n"
        "    email: alice@company.com\n"
        "    status: active\n"
        "    bindings:\n"
        "      linkedin_url: https://www.linkedin.com/in/alice\n"
    )
    from company_brain.wiki.member_bootstrap import ensure_member_wiki

    ensure_member_wiki("alice", sync_notion=False)

    fake = """<<<HR_LINKEDIN>>>
## Bio
Alice is an engineer.

## Posts
- Shipped the wiki
<<<END_HR_LINKEDIN>>>"""

    async def _fake_research(self, member_key, url):
        body = fake.split("<<<HR_LINKEDIN>>>")[1].split("<<<END_HR_LINKEDIN>>>")[0].strip()
        return body, "lsearch"

    monkeypatch.setattr(PullAgent, "_research_linkedin", _fake_research)
    result = PullAgent(load_config()).run(member_key="alice", force=True)
    assert result.get("search_backend") == "lsearch"
    assert result["status"] == "ok"
    from company_brain.wiki.employee_publish import read_employee_wiki_page

    bio = read_employee_wiki_page("alice/bio.md")
    voice = read_employee_wiki_page("alice/voice.md")
    assert "Alice is an engineer" in bio
    assert "Shipped the wiki" in voice


def test_wiki_archive_skips_when_not_due(tmp_path, monkeypatch) -> None:
    env = _hr_env(tmp_path, monkeypatch)
    recent = datetime.now(timezone.utc).isoformat()
    (env["config"] / "members.yaml").write_text(
        "members:\n"
        "  alice:\n"
        "    email: alice@co.com\n"
        "    status: departed\n"
        f"    departed_at: '{recent}'\n"
        "    wiki_archived: false\n"
    )
    result = WikiArchiveAgent(load_config()).run(member_key="alice")
    assert result["status"] == "skipped"
    assert result["reason"] == "not_due"


def test_promote_copies_linkedin_and_department(tmp_path, monkeypatch) -> None:
    env = _hr_env(tmp_path, monkeypatch)
    (env["config"] / "roster.yaml").write_text(
        "people:\n"
        "  jane:\n"
        "    email: jane@co.com\n"
        "    employment_type: contractor\n"
        "    department: growth\n"
        "    linkedin_url: https://www.linkedin.com/in/jane\n"
        "    bridge:\n"
        "      departments: [growth]\n"
    )
    from company_brain.roster_config import promote_roster_to_member

    key = promote_roster_to_member("jane")
    assert key == "jane"
    members = load_members_config()
    assert members.get("jane").department == "growth"
    assert members.get("jane").bindings.linkedin_url.endswith("/jane")
    assert "growth" in members.get("jane").bridge.departments
    assert load_roster_config().get("jane") is None
