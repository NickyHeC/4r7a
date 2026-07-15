"""Tests for Weave implement+prove harness (allow-list, prove, escalate, backends)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from company_brain.agents.admin.change_request import ChangeRequest
from company_brain.agents.admin.weave_allowlist import check_changed_paths, path_allowed
from company_brain.agents.admin.weave_builder_config import (
    BUILDER_CODEX,
    BUILDER_IN_HOUSE,
    BUILDER_OFF,
    resolve_builder,
    weave_builder_config,
)
from company_brain.agents.admin.weave_prove import prove_worktree


def _req(**kwargs) -> ChangeRequest:
    base = dict(
        request_id="abc123def456",
        title="Bump ops yaml",
        body="Please update config/operations.yaml weave channel",
        change_class="config_only",
        requester_member="alice",
        requester_slack_id="UALICE",
    )
    base.update(kwargs)
    return ChangeRequest(**base)


def test_path_allowlist_config_yaml():
    assert path_allowed("config/operations.yaml")
    assert path_allowed("config/nested/foo.json")
    assert path_allowed("docs/weave-requests/abc.md")
    assert not path_allowed("src/company_brain/agents/admin/weave.py")
    assert not path_allowed("config/secret.txt")
    assert not path_allowed("wiki/admin/foo.md")


def test_check_changed_paths_reports_bad():
    ok, bad = check_changed_paths(
        ["config/operations.yaml", "src/company_brain/cli.py"],
    )
    assert ok is False
    assert "src/company_brain/cli.py" in bad


def test_resolve_builder_env(monkeypatch):
    monkeypatch.setenv("WEAVE_BUILDER", "in_house")
    assert resolve_builder() == BUILDER_IN_HOUSE
    monkeypatch.setenv("WEAVE_BUILDER", "off")
    assert resolve_builder() == BUILDER_OFF
    assert resolve_builder("codex") == BUILDER_CODEX


def test_prove_fail_closed_when_builder_unavailable():
    result = prove_worktree(
        Path("."),
        fail_closed=True,
        builder_available=False,
    )
    assert result["ok"] is False
    assert result["reason"] == "builder_unavailable"


def test_prove_soft_when_not_fail_closed():
    result = prove_worktree(
        Path("."),
        fail_closed=False,
        builder_available=False,
    )
    assert result["ok"] is True


def test_escalate_writes_queue(tmp_path, monkeypatch):
    from company_brain.agents.admin import weave_escalate

    written: dict = {}

    def fake_write(rel_path, title, body, **kwargs):
        written["path"] = rel_path
        written["title"] = title
        written["body"] = body
        written["mode"] = kwargs.get("mode")
        return None

    monkeypatch.setattr(weave_escalate, "write_wiki_page", fake_write)
    monkeypatch.setattr(
        weave_escalate,
        "wiki_admin_notifier",
        lambda: MagicMock(emit=lambda *a, **k: True),
    )
    out = weave_escalate.escalate_to_admin_session(
        _req(),
        reason="allowlist_violation",
        disallowed_paths=["src/x.py"],
        sync=False,
    )
    assert out["status"] == "escalated"
    assert written["path"] == "admin/weave-queue.md"
    assert "allowlist_violation" in written["body"]
    assert "src/x.py" in written["body"]


def test_in_house_deterministic_edit(tmp_path):
    from company_brain.agents.admin.weave_in_house import implement_in_house
    from company_brain.agents.admin.weave_worktree import WeaveWorktree

    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = repo / "config"
    cfg.mkdir()
    target = cfg / "operations.yaml"
    target.write_text("slack_platform: {}\n")
    # minimal git repo
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        env={
            **dict(__import__("os").environ),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )
    wt = WeaveWorktree(path=repo, branch="weave/test")
    result = implement_in_house(
        _req(body="Please touch config/operations.yaml thank you"),
        wt,
        use_vm=False,
    )
    assert result.status == "ok"
    assert "config/operations.yaml" in result.changed_paths
    assert "weave:abc123def456" in target.read_text()


def test_weave_agent_codex_unavailable_escalates(monkeypatch):
    from company_brain.agents.admin.weave import WeaveAgent
    from company_brain.config import AppConfig, NotionConfig, WikiConfig

    cfg = AppConfig(notion=NotionConfig(), wiki=WikiConfig(root=Path("/tmp/wiki-x")))
    agent = WeaveAgent(cfg)

    monkeypatch.setattr(
        "company_brain.agents.admin.weave.builder_runtime_available",
        lambda: False,
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.weave.resolve_builder",
        lambda override=None: BUILDER_CODEX,
    )
    escalated = {}

    def fake_esc(req, **kwargs):
        escalated.update(kwargs)
        escalated["id"] = req.request_id
        return {"status": "escalated", "reason": kwargs.get("reason")}

    monkeypatch.setattr(
        "company_brain.agents.admin.weave.escalate_to_admin_session",
        fake_esc,
    )
    monkeypatch.setattr(agent, "_persist_request", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_notify", lambda *a, **k: None)

    out = agent.run(request=_req(), builder="codex", sync=False)
    assert out["status"] == "escalated"
    assert out["reason"] == "builder_unavailable"
    assert escalated.get("reason") == "builder_unavailable"


def test_weave_agent_in_house_allowlist_and_prove(monkeypatch, tmp_path):
    from company_brain.agents.admin.weave import WeaveAgent
    from company_brain.agents.admin.weave_codex import BuilderResult
    from company_brain.agents.admin.weave_worktree import WeaveWorktree
    from company_brain.config import AppConfig, NotionConfig, WikiConfig

    cfg = AppConfig(notion=NotionConfig(), wiki=WikiConfig(root=tmp_path / "wiki"))
    agent = WeaveAgent(cfg)

    repo = tmp_path / "wt"
    repo.mkdir()
    (repo / "config").mkdir()
    (repo / "config" / "operations.yaml").write_text("x: 1\n")
    wt = WeaveWorktree(path=repo, branch="weave/abc123def456")

    monkeypatch.setattr(
        "company_brain.agents.admin.weave.create_weave_worktree",
        lambda branch: wt,
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.weave.implement_in_house",
        lambda req, worktree, use_vm=None: BuilderResult(
            status="ok",
            reason="deterministic_edit",
            changed_paths=["config/operations.yaml"],
        ),
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.weave.prove_worktree",
        lambda *a, **k: {"ok": True, "reason": "passed", "results": []},
    )
    monkeypatch.setattr(wt, "commit_all", lambda msg: True)
    monkeypatch.setattr(wt, "cleanup", lambda: None)
    monkeypatch.setattr(agent, "_open_pr_from_worktree", lambda req, w: "https://example/pr/1")
    monkeypatch.setattr(agent, "_persist_request", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_notify", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_write_proposal_file", lambda root, req: "docs/weave-requests/x.md")

    out = agent.run(request=_req(), builder="in_house", sync=False)
    assert out["status"] == "dispatched"
    assert out["pr_url"] == "https://example/pr/1"
    assert out["builder"] == BUILDER_IN_HOUSE


def test_weave_agent_allowlist_violation_escalates(monkeypatch, tmp_path):
    from company_brain.agents.admin.weave import WeaveAgent
    from company_brain.agents.admin.weave_codex import BuilderResult
    from company_brain.agents.admin.weave_worktree import WeaveWorktree
    from company_brain.config import AppConfig, NotionConfig, WikiConfig

    cfg = AppConfig(notion=NotionConfig(), wiki=WikiConfig(root=tmp_path / "wiki"))
    agent = WeaveAgent(cfg)
    wt = WeaveWorktree(path=tmp_path / "wt", branch="weave/x")
    (tmp_path / "wt").mkdir()

    monkeypatch.setattr(
        "company_brain.agents.admin.weave.create_weave_worktree",
        lambda branch: wt,
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.weave.implement_in_house",
        lambda *a, **k: BuilderResult(
            status="ok",
            changed_paths=["src/company_brain/cli.py"],
        ),
    )
    monkeypatch.setattr(wt, "cleanup", lambda: None)
    monkeypatch.setattr(agent, "_persist_request", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_notify", lambda *a, **k: None)

    escalated = {}

    def fake_esc(req, **kwargs):
        escalated.update(kwargs)
        return {"status": "escalated"}

    monkeypatch.setattr(
        "company_brain.agents.admin.weave.escalate_to_admin_session",
        fake_esc,
    )

    out = agent.run(request=_req(), builder="in_house", sync=False)
    assert out["status"] == "escalated"
    assert out["reason"] == "allowlist_violation"
    assert escalated.get("disallowed_paths") == ["src/company_brain/cli.py"]


def test_builder_config_defaults_include_codex_image():
    cfg = weave_builder_config()
    assert "codex" in cfg["codex_image"] or "registry" in cfg["codex_image"]
    assert cfg["builder"] in {BUILDER_CODEX, BUILDER_IN_HOUSE, BUILDER_OFF}
