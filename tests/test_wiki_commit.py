"""Tests for daily wiki → GitHub backup (wiki_commit)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from company_brain.agents.admin.wiki_commit import (
    EXCLUDE_NAMES,
    WikiCommitAgent,
    authenticated_remote_url,
    mirror_tree,
    volume_signature,
)
from company_brain.agents.gates import StateStore
from company_brain.config import AppConfig, NotionConfig, WikiConfig


def _cfg() -> AppConfig:
    return AppConfig(wiki=WikiConfig(), notion=NotionConfig())


def test_authenticated_remote_url_embeds_token():
    url = authenticated_remote_url("https://github.com/acme/company-wiki.git", "tok123")
    assert url.startswith("https://x-access-token:tok123@github.com/")
    assert "company-wiki.git" in url


def test_mirror_tree_excludes_control_files(tmp_path: Path):
    src = tmp_path / "wiki"
    src.mkdir()
    (src / "page.md").write_text("# hi\n")
    (src / "_index.md").write_text("index\n")
    (src / "_backlinks.json").write_text("{}")
    (src / ".env").write_text("SECRET=1\n")
    dest = tmp_path / "out"
    n = mirror_tree(src, dest)
    assert n >= 1
    assert (dest / "page.md").exists()
    assert not (dest / "_index.md").exists()
    assert not (dest / "_backlinks.json").exists()
    assert not (dest / ".env").exists()
    for name in EXCLUDE_NAMES:
        assert name == ".env" or not (dest / name).exists() or name.startswith("_")


def test_volume_signature_changes_on_edit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "a.md").write_text("one\n")
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setenv("COMPANY_BRAIN_EMPLOYEE_WIKI_DIR", str(tmp_path / "ew"))
    monkeypatch.setenv("COMPANY_BRAIN_RAW_DIR", str(tmp_path / "raw"))
    (tmp_path / "ew").mkdir()
    (tmp_path / "raw").mkdir()
    from company_brain.config import resolve_employee_wiki_dir, resolve_raw_dir, resolve_wiki_dir

    roots = [
        ("wiki", resolve_wiki_dir()),
        ("employee_wiki", resolve_employee_wiki_dir()),
        ("raw", resolve_raw_dir()),
    ]
    s1 = volume_signature(roots)
    (wiki / "a.md").write_text("two\n")
    s2 = volume_signature(roots)
    assert s1 != s2


def test_run_once_skips_when_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import os

    work = tmp_path / "git"
    work.mkdir()
    subprocess.run(["git", "init"], cwd=work, check=True, capture_output=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=work,
        check=True,
        capture_output=True,
        env=env,
    )

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "p.md").write_text("x\n")
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setenv("COMPANY_BRAIN_EMPLOYEE_WIKI_DIR", str(tmp_path / "ew"))
    monkeypatch.setenv("COMPANY_BRAIN_RAW_DIR", str(tmp_path / "raw"))
    (tmp_path / "ew").mkdir()
    (tmp_path / "raw").mkdir()

    state = StateStore(path=tmp_path / "state.json")
    agent = WikiCommitAgent(_cfg())
    agent._state = state

    with (
        patch(
            "company_brain.agents.admin.wiki_commit_config.wiki_commit_enabled",
            return_value=True,
        ),
        patch(
            "company_brain.agents.admin.wiki_commit_config.wiki_commit_remote_url",
            return_value="https://github.com/acme/company-wiki.git",
        ),
        patch(
            "company_brain.agents.admin.wiki_commit_config.wiki_commit_work_dir",
            return_value=work,
        ),
        patch(
            "company_brain.agents.admin.wiki_commit_config.wiki_git_token",
            return_value="tok",
        ),
        patch.object(agent, "_push", return_value=True) as push,
    ):
        first = agent.run_once(force=True)
        assert first["status"] == "ok"
        assert push.call_count == 1
        second = agent.run_once(force=True)
        assert second["status"] == "skipped"
        assert second["reason"] == "unchanged"
        assert push.call_count == 1


def test_run_once_notifies_on_missing_git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(tmp_path / "wiki"))
    (tmp_path / "wiki").mkdir()

    agent = WikiCommitAgent(_cfg())
    agent._state = StateStore(path=tmp_path / "state.json")
    notifier = MagicMock()

    with (
        patch(
            "company_brain.agents.admin.wiki_commit_config.wiki_commit_remote_url",
            return_value="https://github.com/acme/company-wiki.git",
        ),
        patch(
            "company_brain.agents.admin.wiki_commit_config.wiki_commit_work_dir",
            return_value=tmp_path / "missing",
        ),
        patch(
            "company_brain.agents.admin.wiki_commit.wiki_admin_notifier",
            return_value=notifier,
        ),
    ):
        result = agent.run_once(force=True)

    assert result["status"] == "error"
    assert "not a git repo" in result["error"]
    notifier.emit.assert_called_once()
    assert notifier.emit.call_args[0][0].severity == "actionable"


def test_should_run_respects_daily_gate(tmp_path: Path):
    agent = WikiCommitAgent(_cfg())
    agent._state = StateStore(path=tmp_path / "state.json")
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    agent._state.set("wiki_commit:last_push_date", today)

    with (
        patch(
            "company_brain.agents.admin.wiki_commit_config.wiki_commit_enabled",
            return_value=True,
        ),
        patch(
            "company_brain.agents.admin.wiki_commit_config.wiki_commit_remote_url",
            return_value="https://github.com/acme/company-wiki.git",
        ),
        patch(
            "company_brain.agents.admin.wiki_commit_config.wiki_commit_hour_utc",
            return_value=0,
        ),
    ):
        assert agent.should_run() is False
        assert agent.should_run(force=True) is True
