"""Tests for guided install profile, credentials, foundation, orchestrator helpers."""

from __future__ import annotations

from pathlib import Path

from company_brain.agents.admin.install_credentials import checklist_rows, format_checklist
from company_brain.agents.admin.install_foundation import run_foundation_checks
from company_brain.agents.admin.install_orchestrator import (
    ONBOARD_SEQUENCE,
    cleanup_checklist,
)
from company_brain.agents.admin.install_profile import (
    DEPARTMENT_ORDER,
    apply_profile_flags,
    default_profile_dict,
    load_install_profile,
    profile_from_dict,
    save_install_profile,
    set_platform_enabled,
)


def test_default_profile_enables_core_departments() -> None:
    profile = profile_from_dict(default_profile_dict())
    assert profile.department_onboarding_order() == list(DEPARTMENT_ORDER)
    assert profile.platform_enabled("github")
    assert profile.notion_sync is True
    assert profile.bridge is False


def test_disable_department_disables_platforms(tmp_path: Path) -> None:
    profile = apply_profile_flags(
        disable_department=("finance",),
        disable_platform=("discord",),
        config_dir=tmp_path,
    )
    assert not profile.department_enabled("finance")
    assert not profile.platform_enabled("mercury")
    assert not profile.platform_enabled("discord")
    assert profile.platform_enabled("github")
    reloaded = load_install_profile(tmp_path)
    assert not reloaded.platform_enabled("discord")


def test_credentials_checklist_filters_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MERCURY_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    profile = apply_profile_flags(
        disable_department=("finance", "growth", "product", "hr"),
        disable_platform=("gmail", "granola", "linear", "slack"),
        brain_repo_url="https://github.com/acme/4r7a",
        wiki_repo_url="https://github.com/acme/company-wiki",
        config_dir=tmp_path,
    )
    rows = checklist_rows(profile)
    keys = {r["key"] for r in rows}
    assert "Private 4r7a (brain) repo URL" in keys or any(
        "brain" in r["label"].lower() for r in rows
    )
    assert "MERCURY_TOKEN" not in keys
    assert "DISCORD_BOT_TOKEN" not in keys
    text = format_checklist(profile)
    assert "MERCURY_TOKEN" not in text


def test_foundation_requires_brain_repo(tmp_path: Path) -> None:
    profile = profile_from_dict(default_profile_dict())
    profile.brain_repo_url = ""
    profile.wiki_git_backup = False
    save_install_profile(profile, tmp_path)
    # run against in-memory profile object
    report = run_foundation_checks(profile)
    ids = {c.check_id: c for c in report.checks}
    assert ids["brain_repo_url"].ok is False
    assert report.ok is False


def test_onboard_sequence_order() -> None:
    assert list(ONBOARD_SEQUENCE.keys()) == [
        "engineering",
        "operations",
        "product",
        "growth",
        "finance",
        "hr",
    ]
    assert ONBOARD_SEQUENCE["engineering"][0] == "github"


def test_cleanup_checklist_requires_disabled_list(tmp_path: Path) -> None:
    profile = apply_profile_flags(disable_platform=("posthog",), config_dir=tmp_path)
    text = cleanup_checklist(profile)
    assert "posthog" in text
    assert "deleted automatically" in text.lower()


def test_set_platform_enabled_roundtrip(tmp_path: Path) -> None:
    profile = (
        load_install_profile(tmp_path)
        if (tmp_path / "install_profile.yaml").exists()
        else profile_from_dict({})
    )
    set_platform_enabled(profile, "ramp", False)
    save_install_profile(profile, tmp_path)
    again = load_install_profile(tmp_path)
    assert again.platform_enabled("ramp") is False
