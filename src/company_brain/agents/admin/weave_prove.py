"""Fail-closed prove bar for Weave implement+prove worktrees."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from company_brain.agents.admin.weave_builder_config import weave_builder_config

logger = logging.getLogger(__name__)


def prove_commands(*, workdir: Path | None = None) -> list[list[str]]:
    """Commands to run against an ephemeral Weave worktree (host tools).

    ``ruff``/``pytest`` run with cwd=workdir; paths are relative to that tree.
    """
    del workdir  # cwd is set by prove_worktree
    return [
        ["ruff", "check", "."],
        ["pytest", "-q", "--tb=line"],
        [
            "company-brain",
            "doctor",
            "code",
            "--min-score",
            "85",
            "--no-history",
        ],
    ]


def _run_cmd(cmd: list[str], *, cwd: Path) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return 1, str(exc)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def prove_worktree(
    workdir: Path,
    *,
    fail_closed: bool | None = None,
    builder_available: bool = True,
) -> dict[str, Any]:
    """Run the Weave prove bar on ``workdir``.

    When ``fail_closed`` is True (default) and the builder/sandbox runtime was
    unavailable, returns ``ok=False`` without running commands.
    """
    cfg = weave_builder_config()
    if fail_closed is None:
        fail_closed = bool(cfg.get("prove_fail_closed", True))

    if not builder_available:
        if fail_closed:
            return {
                "ok": False,
                "reason": "builder_unavailable",
                "results": [],
            }
        return {"ok": True, "reason": "builder_unavailable_soft", "results": []}

    results: list[dict[str, Any]] = []
    for cmd in prove_commands(workdir=workdir):
        # doctor is project-global; run from workdir still for ruff/pytest layout
        cwd = workdir if cmd[0] != "company-brain" else workdir
        if cmd[0] == "ruff" and shutil.which("ruff") is None:
            results.append({"cmd": cmd, "ok": False, "output": "ruff not found"})
            return {"ok": False, "reason": "prove_tool_missing", "results": results}
        if cmd[0] == "pytest" and shutil.which("pytest") is None:
            results.append({"cmd": cmd, "ok": False, "output": "pytest not found"})
            return {"ok": False, "reason": "prove_tool_missing", "results": results}
        code, output = _run_cmd(cmd, cwd=cwd)
        results.append({"cmd": cmd, "ok": code == 0, "output": output[-2000:]})
        if code != 0:
            logger.info("Weave prove failed (%s): %s", cmd, output[-400:])
            return {"ok": False, "reason": "prove_failed", "results": results}
    return {"ok": True, "reason": "passed", "results": results}
