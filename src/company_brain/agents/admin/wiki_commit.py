"""Wiki Commit — persistent daily export of the MD volume to an admin-only GitHub repo.

Reads the local wiki / employee_wiki / raw trees (source of truth), mirrors them into
a dedicated git workdir, and pushes one commit to ``main`` when dirty. GitHub is
backup + version history only — never a live read plane.

SDK: Neither (deterministic git/fs). Independent of other agents.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from company_brain.agents.admin import wiki_commit_config as cfg
from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.config import (
    AppConfig,
    resolve_employee_wiki_dir,
    resolve_raw_dir,
    resolve_wiki_dir,
)
from company_brain.llm.admin_notify import wiki_admin_notifier
from company_brain.notify import ACTIONABLE, Signal

STATE_PUSH_DATE = "wiki_commit:last_push_date"
STATE_SIGNATURE = "wiki_commit:last_signature"

# Regenerable / secret / junk — never export into the backup repo.
EXCLUDE_NAMES = frozenset(
    {
        "_index.md",
        "_backlinks.json",
        "_absorb_log.json",
        ".env",
        ".DS_Store",
        "__pycache__",
        "credentials.json",
        "state.json",
        "bridge-tokens.json",
    }
)
EXCLUDE_SUFFIXES = (".pyc", ".pyo")

EXPORT_ROOTS = (
    ("wiki", resolve_wiki_dir),
    ("employee_wiki", resolve_employee_wiki_dir),
    ("raw", resolve_raw_dir),
)


def _should_skip(name: str) -> bool:
    if name in EXCLUDE_NAMES or name.startswith(".git"):
        return True
    return name.endswith(EXCLUDE_SUFFIXES)


def volume_signature(roots: list[tuple[str, Path]] | None = None) -> str:
    """Cheap signature over export roots (path + size + mtime)."""
    pairs = roots or [(label, fn()) for label, fn in EXPORT_ROOTS]
    h = hashlib.sha256()
    for label, root in sorted(pairs, key=lambda x: x[0]):
        h.update(label.encode())
        if not root.is_dir():
            h.update(b"missing")
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not _should_skip(d))
            for name in sorted(filenames):
                if _should_skip(name):
                    continue
                path = Path(dirpath) / name
                try:
                    st = path.stat()
                except OSError:
                    continue
                rel = path.relative_to(root).as_posix()
                h.update(f"{rel}:{st.st_size}:{int(st.st_mtime_ns)}".encode())
    return h.hexdigest()[:32]


def mirror_tree(src: Path, dest: Path) -> int:
    """Mirror ``src`` into ``dest`` with excludes. Returns files copied/updated."""
    copied = 0
    if not src.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    wanted: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if not _should_skip(d)]
        rel_dir = Path(dirpath).relative_to(src)
        target_dir = dest / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in filenames:
            if _should_skip(name):
                continue
            rel = (rel_dir / name).as_posix()
            wanted.add(rel)
            s = Path(dirpath) / name
            d = dest / rel
            try:
                if d.exists():
                    ss, ds = s.stat(), d.stat()
                    if ss.st_mtime_ns == ds.st_mtime_ns and ss.st_size == ds.st_size:
                        continue
                shutil.copy2(s, d)
                copied += 1
            except OSError:
                continue

    # Remove dest files not present in source (keep .git only at work_dir root).
    if dest.is_dir():
        for dirpath, dirnames, filenames in os.walk(dest, topdown=False):
            for name in filenames:
                path = Path(dirpath) / name
                rel = path.relative_to(dest).as_posix()
                if rel not in wanted:
                    try:
                        path.unlink()
                    except OSError:
                        pass
            for name in dirnames:
                path = Path(dirpath) / name
                try:
                    if not any(path.iterdir()):
                        path.rmdir()
                except OSError:
                    pass
    return copied


def authenticated_remote_url(remote: str, token: str) -> str:
    """Embed token for HTTPS push without mutating stored remotes permanently."""
    if not token or not remote:
        return remote
    parsed = urlparse(remote)
    if parsed.scheme not in ("http", "https"):
        return remote
    netloc = parsed.netloc
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[-1]
    userinfo = f"x-access-token:{token}@{netloc}"
    return urlunparse(
        (parsed.scheme, userinfo, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class WikiCommitAgent(BaseAgent):
    """Persistent agent: daily MD volume → admin-only company-wiki git push."""

    name = "wiki_commit"
    track_duration = False

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()

    def should_run(self, **kwargs: Any) -> bool:
        force = bool(kwargs.get("force"))
        if not cfg.wiki_commit_enabled() and not force:
            return False
        if not cfg.wiki_commit_remote_url() and not force:
            return False
        if force:
            return True
        now = datetime.now(timezone.utc)
        if now.hour < cfg.wiki_commit_hour_utc():
            return False
        today = now.date().isoformat()
        if self._state.get(STATE_PUSH_DATE) == today:
            return False
        return True

    def run(self, *, once: bool = True, force: bool = False, **kwargs: Any) -> Any:
        if once:
            return self.run_once(force=force)
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        from company_brain.admin_console.heartbeats import record_heartbeat

        interval = cfg.wiki_commit_poll_interval_minutes()
        self.logger.info(
            "wiki_commit persistent loop (every %d min, hour_utc>=%d)",
            interval,
            cfg.wiki_commit_hour_utc(),
        )
        while True:
            record_heartbeat(self.name, detail="idle")
            try:
                if self.should_run():
                    self.run_once(force=False)
                    record_heartbeat(self.name, detail="pass")
            except Exception:
                self.logger.exception("wiki_commit pass failed")
            await asyncio.sleep(interval * 60)

    def run_once(self, *, force: bool = False) -> dict[str, Any]:
        remote = cfg.wiki_commit_remote_url()
        work_dir = cfg.wiki_commit_work_dir()
        branch = cfg.wiki_commit_branch()
        token = cfg.wiki_git_token()

        if not remote:
            return self._fail("wiki_commit: remote_url not configured", notify=True)

        if not work_dir.is_dir() or not (work_dir / ".git").is_dir():
            return self._fail(
                "wiki_commit: work_dir is not a git repo "
                f"({work_dir}). Create the private company-wiki repo and clone it "
                "there first (bootstrap is tabled under admin onboarding).",
                notify=True,
            )

        sig = volume_signature()
        # Unchanged volume never pushes (force only bypasses hour / once-per-day gates).
        if self._state.get(STATE_SIGNATURE) == sig:
            today = datetime.now(timezone.utc).date().isoformat()
            self._state.set(STATE_PUSH_DATE, today)
            self.logger.info("wiki_commit: volume unchanged; skipping push")
            return {"status": "skipped", "reason": "unchanged", "signature": sig}

        roots = [(label, fn()) for label, fn in EXPORT_ROOTS]
        copied = 0
        for label, src in roots:
            copied += mirror_tree(src, work_dir / label)

        status = _run_git(["status", "--porcelain"], cwd=work_dir)
        if status.returncode != 0:
            return self._fail(
                f"wiki_commit: git status failed: {(status.stderr or '')[-300:]}",
                notify=True,
            )
        dirty = bool((status.stdout or "").strip())
        if not dirty:
            today = datetime.now(timezone.utc).date().isoformat()
            self._state.set(STATE_PUSH_DATE, today)
            self._state.set(STATE_SIGNATURE, sig)
            return {
                "status": "skipped",
                "reason": "clean",
                "signature": sig,
                "copied": copied,
            }

        date = datetime.now(timezone.utc).date().isoformat()
        msg = f"wiki backup {date}"
        add = _run_git(["add", "-A"], cwd=work_dir)
        if add.returncode != 0:
            return self._fail(
                f"wiki_commit: git add failed: {(add.stderr or '')[-300:]}",
                notify=True,
            )

        commit_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "wiki_commit",
            "GIT_AUTHOR_EMAIL": "wiki-commit@company-brain.local",
            "GIT_COMMITTER_NAME": "wiki_commit",
            "GIT_COMMITTER_EMAIL": "wiki-commit@company-brain.local",
        }
        commit = _run_git(["commit", "-m", msg], cwd=work_dir, env=commit_env)
        out = (commit.stdout or "") + (commit.stderr or "")
        if commit.returncode != 0 and "nothing to commit" not in out:
            return self._fail(
                f"wiki_commit: git commit failed: {(commit.stderr or '')[-300:]}",
                notify=True,
            )

        push_ok = self._push(work_dir, remote, branch, token)
        if not push_ok:
            # One retry
            push_ok = self._push(work_dir, remote, branch, token)
        if not push_ok:
            return self._fail(
                f"wiki_commit: git push to {branch} failed (retried once). "
                "Check COMPANY_BRAIN_WIKI_GIT_TOKEN and remote access.",
                notify=True,
            )

        today = datetime.now(timezone.utc).date().isoformat()
        self._state.set(STATE_PUSH_DATE, today)
        self._state.set(STATE_SIGNATURE, sig)
        self.logger.info("wiki_commit: pushed %s (%s)", msg, sig)
        return {
            "status": "ok",
            "commit": msg,
            "signature": sig,
            "copied": copied,
            "branch": branch,
        }

    def _push(self, work_dir: Path, remote: str, branch: str, token: str) -> bool:
        # Never force-push. Use authenticated URL for this push only.
        url = authenticated_remote_url(remote, token) if token else remote
        # Ensure local branch tracks main; checkout main if needed.
        _run_git(["checkout", "-B", branch], cwd=work_dir)
        push = _run_git(["push", url, f"HEAD:{branch}"], cwd=work_dir)
        if push.returncode != 0:
            self.logger.warning("git push failed: %s", (push.stderr or "")[-400:])
            return False
        return True

    def _fail(self, text: str, *, notify: bool) -> dict[str, Any]:
        self.logger.error(text)
        if notify:
            wiki_admin_notifier().emit(Signal(text=text, severity=ACTIONABLE))
        return {"status": "error", "error": text}
