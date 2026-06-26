"""Heuristics for whether closed-task activity warrants a new binding."""

from __future__ import annotations

import re
from typing import Any

from company_brain.agents.engineering.linear.task_bindings import TaskBinding

FOLLOW_UP_PATTERNS = (
    re.compile(r"\bfollow[\s-]?up\b", re.I),
    re.compile(r"\bnew request\b", re.I),
    re.compile(r"\bseparate (issue|task|ticket)\b", re.I),
    re.compile(r"\bre:?open\b", re.I),
)

SIGNIFICANT_MIN_BODY = 120


def evaluate_follow_up(
    closed_binding: TaskBinding,
    new_activity: dict[str, Any],
) -> str:
    """Return ``new_task`` when activity on a closed binding should spawn a follow-up."""
    if not _binding_is_terminal(closed_binding):
        return "ignore"

    body = str(new_activity.get("body") or new_activity.get("snippet") or "")
    subject = str(new_activity.get("subject") or "")

    if any(p.search(subject) or p.search(body) for p in FOLLOW_UP_PATTERNS):
        return "new_task"

    if len(body.strip()) >= SIGNIFICANT_MIN_BODY and subject.strip():
        original_subject = (closed_binding.title or "").strip().lower()
        if subject.strip().lower() != original_subject:
            return "new_task"

    if new_activity.get("new_thread") and body.strip():
        return "new_task"

    return "ignore"


def _binding_is_terminal(binding: TaskBinding) -> bool:
    for entry in reversed(binding.status_track):
        if entry.get("platform") == "linear" and entry.get("field") == "status":
            return str(entry.get("value", "")).lower() in ("done", "canceled", "cancelled")
    gmail = binding.platforms.get("gmail") or {}
    if gmail.get("archived"):
        return True
    return False
