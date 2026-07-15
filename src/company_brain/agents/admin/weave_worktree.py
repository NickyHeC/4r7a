"""Ephemeral git worktree helpers for Weave guest-only edits."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from company_brain.config import PROJECT_ROOT

logger = logging.getLogger(__name__)


@dataclass
class WeaveWorktree:
    path: Path
    branch: str
    cleanup_root: Path | None = None

    def changed_paths(self) -> list[str]:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=self.path,
            capture_output=True,
            text=True,
        )
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=self.path,
            capture_output=True,
            text=True,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=self.path,
            capture_output=True,
            text=True,
        )
        names: list[str] = []
        for blob in (proc.stdout or "", staged.stdout or "", untracked.stdout or ""):
            for line in blob.splitlines():
                line = line.strip()
                if line and line not in names:
                    names.append(line)
        return names

    def commit_all(self, message: str) -> bool:
        subprocess.run(["git", "add", "-A"], cwd=self.path, check=False, capture_output=True)
        commit = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=self.path,
            capture_output=True,
            text=True,
        )
        out = (commit.stdout or "") + (commit.stderr or "")
        if commit.returncode != 0 and "nothing to commit" not in out:
            logger.warning("weave worktree commit failed: %s", commit.stderr[-400:])
            return False
        return True

    def push(self) -> bool:
        push = subprocess.run(
            ["git", "push", "-u", "origin", self.branch],
            cwd=self.path,
            capture_output=True,
            text=True,
        )
        if push.returncode != 0:
            logger.warning("weave worktree push failed: %s", push.stderr[-400:])
            return False
        return True

    def cleanup(self) -> None:
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(self.path)],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )
        except OSError:
            pass
        if self.cleanup_root and self.cleanup_root.exists():
            shutil.rmtree(self.cleanup_root, ignore_errors=True)


def create_weave_worktree(branch: str, *, base: Path | None = None) -> WeaveWorktree:
    """Create an ephemeral worktree from ``base`` (default project root) on ``branch``."""
    base = base or PROJECT_ROOT
    root = Path(tempfile.mkdtemp(prefix="weave-wt-"))
    path = root / "repo"
    # Prefer worktree so we share objects; fall back to local clone.
    add = subprocess.run(
        ["git", "worktree", "add", "-B", branch, str(path), "HEAD"],
        cwd=base,
        capture_output=True,
        text=True,
    )
    if add.returncode != 0:
        logger.info("git worktree add failed (%s); cloning locally", add.stderr[-200:])
        clone = subprocess.run(
            ["git", "clone", "--local", str(base), str(path)],
            capture_output=True,
            text=True,
        )
        if clone.returncode != 0:
            shutil.rmtree(root, ignore_errors=True)
            raise RuntimeError(f"failed to create weave worktree: {clone.stderr[-400:]}")
        subprocess.run(
            ["git", "checkout", "-B", branch],
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
        )
        return WeaveWorktree(path=path, branch=branch, cleanup_root=root)
    return WeaveWorktree(path=path, branch=branch, cleanup_root=root)
