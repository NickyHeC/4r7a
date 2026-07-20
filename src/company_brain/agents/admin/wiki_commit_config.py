"""Config for daily wiki → GitHub backup (``admin.wiki_commit``)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from company_brain.agents.admin.llm_ops_config import load_operations_raw
from company_brain.config import PROJECT_ROOT

_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "hour_utc": 6,
    "remote_url": "",
    "work_dir": "",
    "branch": "main",
    "poll_interval_minutes": 60,
}

TOKEN_ENV = "COMPANY_BRAIN_WIKI_GIT_TOKEN"
WORK_DIR_ENV = "COMPANY_BRAIN_WIKI_GIT_DIR"


def wiki_commit_config() -> dict[str, Any]:
    raw = load_operations_raw().get("admin") or {}
    block = dict(_DEFAULTS)
    nested = raw.get("wiki_commit") or {}
    if isinstance(nested, dict):
        block.update({k: v for k, v in nested.items() if v is not None})
    return block


def wiki_commit_enabled() -> bool:
    return bool(wiki_commit_config().get("enabled"))


def wiki_commit_hour_utc() -> int:
    try:
        return int(wiki_commit_config().get("hour_utc") or 6)
    except (TypeError, ValueError):
        return 6


def wiki_commit_branch() -> str:
    return str(wiki_commit_config().get("branch") or "main").strip() or "main"


def wiki_commit_remote_url() -> str:
    return str(wiki_commit_config().get("remote_url") or "").strip()


def wiki_commit_poll_interval_minutes() -> int:
    try:
        return max(5, int(wiki_commit_config().get("poll_interval_minutes") or 60))
    except (TypeError, ValueError):
        return 60


def wiki_commit_work_dir() -> Path:
    env = os.getenv(WORK_DIR_ENV, "").strip()
    if env:
        return Path(env)
    configured = str(wiki_commit_config().get("work_dir") or "").strip()
    if configured:
        return Path(configured)
    return PROJECT_ROOT / ".wiki_git"


def wiki_git_token() -> str:
    return os.getenv(TOKEN_ENV, "").strip()
