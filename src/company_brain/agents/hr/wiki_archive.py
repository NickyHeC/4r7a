"""Wiki Archive — T+30 push employee wiki to GitHub branch, then unmount.

Reuses wiki-git remote/token from ``wiki_commit``. Branch:
``archive/employee/{member}`` (never ``main``).

SDK: Neither (git + filesystem).
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from company_brain.agents.admin import wiki_commit_config as wiki_git
from company_brain.agents.admin.wiki_commit import authenticated_remote_url
from company_brain.agents.base import BaseAgent
from company_brain.agents.hr import hr_config as cfg
from company_brain.agents.hr.hiring_log import append_hiring_log
from company_brain.config import resolve_employee_wiki_dir
from company_brain.members_config import load_members_config, update_member


class WikiArchiveAgent(BaseAgent):
    """Archive departed employee wikis after the configured delay."""

    name = "wiki_archive"

    def run(
        self,
        *,
        member_key: str = "",
        force: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        key = (member_key or "").strip()
        if key:
            return self._archive_one(key, force=force)

        due = _due_members(force=force)
        results: dict[str, Any] = {}
        for k in due:
            results[k] = self._archive_one(k, force=force)
        return {"status": "ok", "archived": results, "due_count": len(due)}

    def _archive_one(self, member_key: str, *, force: bool) -> dict[str, Any]:
        members = load_members_config()
        spec = members.get(member_key)
        if spec is None:
            return {"status": "skipped", "reason": "unknown_member"}
        if spec.is_active and not force:
            return {"status": "skipped", "reason": "still_active"}
        if spec.wiki_archived and not force:
            return {"status": "skipped", "reason": "already_archived"}
        if not force and not _is_due(spec.departed_at):
            return {
                "status": "skipped",
                "reason": "not_due",
                "departed_at": spec.departed_at,
            }

        root = resolve_employee_wiki_dir() / member_key
        if not root.is_dir():
            update_member(member_key, wiki_archived=True)
            append_hiring_log(
                f"Wiki archive — {member_key}",
                "No employee wiki tree on volume; marked `wiki_archived`.",
                trigger="wiki_archive",
                why=member_key,
            )
            return {"status": "ok", "member": member_key, "note": "missing_tree_marked"}

        branch = f"archive/employee/{member_key}"
        push = _push_archive_branch(member_key, root, branch=branch)
        if push.get("status") != "ok":
            return {"status": "error", "member": member_key, "push": push}

        shutil.rmtree(root)
        update_member(member_key, wiki_archived=True)
        append_hiring_log(
            f"Wiki archive — {member_key}",
            f"- **Branch:** `{branch}`\n"
            f"- **Remote:** `{wiki_git.wiki_commit_remote_url() or '—'}`\n"
            "- **Volume:** employee wiki tree removed",
            trigger="wiki_archive",
            why=member_key,
        )
        return {
            "status": "ok",
            "member": member_key,
            "branch": branch,
            "push": push,
            "unmounted": True,
        }


def _due_members(*, force: bool) -> list[str]:
    out: list[str] = []
    for key, spec in load_members_config().members.items():
        if spec.is_active:
            continue
        if spec.wiki_archived and not force:
            continue
        if force or _is_due(spec.departed_at):
            out.append(key)
    return out


def _is_due(departed_at: str) -> bool:
    if not (departed_at or "").strip():
        return False
    try:
        raw = departed_at.strip().replace("Z", "+00:00")
        when = datetime.fromisoformat(raw)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    delay = timedelta(days=cfg.archive_delay_days())
    return datetime.now(timezone.utc) >= when.astimezone(timezone.utc) + delay


def _push_archive_branch(member_key: str, src: Path, *, branch: str) -> dict[str, Any]:
    remote = wiki_git.wiki_commit_remote_url()
    token = wiki_git.wiki_git_token()
    if not remote:
        return {"status": "error", "reason": "remote_url_not_configured"}

    work = wiki_git.wiki_commit_work_dir() / f"archive_{member_key}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    def git(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=work,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    init = git(["init"])
    if init.returncode != 0:
        return {"status": "error", "reason": "git_init", "stderr": init.stderr}

    dest = work / "employee_wiki" / member_key
    shutil.copytree(src, dest)

    git(["checkout", "-B", branch])
    git(["add", "-A"])
    commit = git(
        [
            "-c",
            "user.email=wiki-archive@company-brain.local",
            "-c",
            "user.name=company-brain wiki_archive",
            "commit",
            "-m",
            f"Archive employee wiki for {member_key}",
        ]
    )
    if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
        return {"status": "error", "reason": "git_commit", "stderr": commit.stderr}

    auth_remote = authenticated_remote_url(remote, token)
    git(["remote", "remove", "origin"])
    add = git(["remote", "add", "origin", auth_remote])
    if add.returncode != 0:
        return {"status": "error", "reason": "remote_add", "stderr": add.stderr}

    push = git(["push", "-u", "origin", branch, "--force"])
    # scrub workdir with credentials in remote
    shutil.rmtree(work, ignore_errors=True)
    if push.returncode != 0:
        return {"status": "error", "reason": "git_push", "stderr": push.stderr}
    return {"status": "ok", "branch": branch, "remote": remote}
