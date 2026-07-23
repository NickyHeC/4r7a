"""Upstream sync path filtering + config helpers."""

from __future__ import annotations

from company_brain.agents.admin.install_profile import InstallProfile
from company_brain.agents.admin.upstream_sync import (
    ALWAYS_SAFE_PREFIXES,
    allowed_path_prefixes,
    filter_changed_paths,
    github_slug_from_url,
    path_allowed,
)


def test_github_slug_from_url() -> None:
    assert github_slug_from_url("https://github.com/acme/4r7a.git") == "acme/4r7a"
    assert github_slug_from_url("git@github.com:acme/4r7a.git") is None


def test_path_filter_always_safe() -> None:
    prefixes = list(ALWAYS_SAFE_PREFIXES)
    assert path_allowed("src/company_brain/runtime/fleet_gate.py", prefixes)
    assert not path_allowed("src/company_brain/agents/growth/discord/foo.py", prefixes)


def test_path_filter_includes_enabled_platform() -> None:
    profile = InstallProfile(
        platforms={
            "discord": {"enabled": True, "department": "growth"},
            "github": {"enabled": False, "department": "engineering"},
        },
        departments={"growth": True, "engineering": True},
    )
    prefixes = allowed_path_prefixes(profile)
    paths = [
        "src/company_brain/runtime/runtime.py",
        "src/company_brain/agents/growth/discord/gateway.py",
        "src/company_brain/agents/engineering/github/open_pr.py",
        "README.md",
    ]
    selected = filter_changed_paths(paths, prefixes)
    assert "src/company_brain/runtime/runtime.py" in selected
    assert "src/company_brain/agents/growth/discord/gateway.py" in selected
    assert "src/company_brain/agents/engineering/github/open_pr.py" not in selected
    assert "README.md" not in selected


def test_ensure_wiki_repo_skips_when_reachable(monkeypatch, tmp_path) -> None:
    from company_brain.agents.admin import install_foundation as found
    from company_brain.agents.admin.install_profile import InstallProfile

    profile = InstallProfile(
        brain_repo_url="https://github.com/acme/4r7a",
        wiki_repo_url="https://github.com/acme/company-wiki",
        wiki_git_backup=True,
    )
    monkeypatch.setattr(found, "_repo_accessible", lambda url: True)
    monkeypatch.setattr(found, "save_install_profile", lambda p: tmp_path / "x.yaml")
    _, check = found.ensure_wiki_repo(profile, create=True)
    assert check.ok is True
    assert "already reachable" in check.message
