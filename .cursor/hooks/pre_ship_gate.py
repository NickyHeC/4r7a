#!/usr/bin/env python3
"""Stop hook: run the company-brain pre-ship gate after code-changing agent turns.

Reads Cursor stop-event JSON on stdin. When the working tree has relevant code
changes, runs:

  ruff check .
  ruff format --check .
  pytest -q
  company-brain doctor code --min-score 85

On failure (and while under loop_limit), returns followup_message so the agent
fixes and re-runs. On success / skip / abort: prints ``{}``.

See docs/hygiene_checklist.md and .cursor/rules/governance.mdc §5.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEVANT_PREFIXES = (
    "src/",
    "tests/",
    "config/",
    "Smolfile",
    "pyproject.toml",
    ".cursor/rules/",
    ".cursor/hooks/",
)
MAX_OUTPUT = 3500
LOOP_CAP = 2

COMMANDS: list[tuple[str, list[str]]] = [
    ("ruff check", ["ruff", "check", "."]),
    ("ruff format --check", ["ruff", "format", "--check", "."]),
    ("pytest -q", ["pytest", "-q"]),
    (
        "company-brain doctor code",
        ["company-brain", "doctor", "code", "--min-score", "85"],
    ),
]


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


def _read_stdin() -> dict:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _relevant_paths() -> list[str]:
    """Return changed paths that warrant the pre-ship gate."""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:
        print(f"pre_ship_gate: git status failed: {exc}", file=sys.stderr)
        return []

    paths: list[str] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        # porcelain: XY PATH or XY ORIG -> PATH
        entry = line[3:].strip()
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1].strip()
        entry = entry.strip('"')
        if entry == ".DS_Store" or entry.endswith("/.DS_Store"):
            continue
        if any(entry == p or entry.startswith(p) for p in RELEVANT_PREFIXES):
            paths.append(entry)
    return paths


def _run(label: str, cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=540,
            check=False,
        )
    except FileNotFoundError:
        return False, f"{label}: command not found ({cmd[0]})"
    except subprocess.TimeoutExpired:
        return False, f"{label}: timed out"
    except Exception as exc:
        return False, f"{label}: {exc}"

    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        return True, ""
    clipped = out.strip()
    if len(clipped) > MAX_OUTPUT:
        clipped = clipped[:MAX_OUTPUT] + "\n…(truncated)…"
    return False, f"{label} failed (exit {proc.returncode}):\n{clipped}"


def main() -> int:
    payload = _read_stdin()
    status = str(payload.get("status") or "completed")
    loop_count = int(payload.get("loop_count") or 0)

    if status in {"aborted", "error"}:
        _emit({})
        return 0

    if loop_count >= LOOP_CAP:
        print(
            f"pre_ship_gate: loop_count={loop_count} >= {LOOP_CAP}; skipping",
            file=sys.stderr,
        )
        _emit({})
        return 0

    changed = _relevant_paths()
    if not changed:
        print("pre_ship_gate: no relevant code changes; skip", file=sys.stderr)
        _emit({})
        return 0

    print(
        f"pre_ship_gate: running pre-ship gate ({len(changed)} relevant path(s))",
        file=sys.stderr,
    )
    failures: list[str] = []
    for label, cmd in COMMANDS:
        ok, detail = _run(label, cmd)
        if not ok:
            failures.append(detail)

    if not failures:
        print("pre_ship_gate: all checks passed", file=sys.stderr)
        _emit({})
        return 0

    body = (
        "Pre-ship gate failed after your last turn "
        "(auto-run via `.cursor/hooks/pre_ship_gate.py`). "
        "Fix the failures below, then stop so the gate can re-run.\n\n" + "\n\n".join(failures)
    )
    _emit({"followup_message": body})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
