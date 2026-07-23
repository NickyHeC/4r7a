"""Granola Task Agent — extract meeting action items and bind to Linear.

Origin-aware fan-out: wiki binding + Linear issue + Notion row per action item.

SDK: Neither (deterministic extraction heuristics).
"""

from __future__ import annotations

import re
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.engineering.linear import linear_client
from company_brain.agents.engineering.linear.task_bindings import TaskBindingStore
from company_brain.agents.engineering.shared.linear_config import (
    default_priority,
    task_class_fan_out,
    team_id,
    team_key,
)
from company_brain.config import AppConfig

ACTION_LINE_RE = re.compile(
    r"^[\s>*\-]*\(?\[?[ xX]?\]?\)?[\s]*(.+)$",
)
ACTION_KEYWORDS = (
    "action item",
    "action:",
    "todo",
    "to-do",
    "follow up",
    "follow-up",
    "next step",
    "will do",
    "assigned to",
)


class TaskAgent(BaseAgent):
    """Create Linear tasks from Granola meeting action items."""

    name = "task"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._bindings = TaskBindingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return linear_client.linear_is_configured()

    def run(
        self,
        *,
        notes: list[dict[str, Any]],
        meeting_date: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if "linear" not in task_class_fan_out("meeting_action"):
            return {"status": "skipped", "reason": "fan_out"}

        created = 0
        for note in notes:
            note_id = str(note.get("note_id") or note.get("id") or "")
            detail = note.get("detail") or note
            if not note_id:
                continue
            items = extract_action_items(detail)
            if not items:
                continue
            for item in items:
                if self._bindings.find_by_granola_note(f"{note_id}:{item[:40]}"):
                    continue
                try:
                    self._create_task(note_id, meeting_date, detail, item)
                    created += 1
                except Exception:
                    self.logger.exception("task failed for note %s", note_id)

        return {"created": created, "notes": len(notes)}

    def _create_task(
        self,
        note_id: str,
        meeting_date: str,
        detail: dict[str, Any],
        item_text: str,
    ) -> None:
        meeting_title = detail.get("title") or "Meeting"
        title = f"[Meeting] {item_text[:200]}"
        description = (
            f"From Granola meeting **{meeting_title}** ({meeting_date}).\n\n"
            f"**Action item:** {item_text}\n\n"
            f"**Granola note:** `{note_id}`"
        )
        issue = linear_client.create_issue(
            title=title,
            description=description,
            team_id=team_id() or None,
            team_key=team_key() or None,
            priority=default_priority(),
        )
        binding = self._bindings.create_granola_binding(
            note_id=f"{note_id}:{item_text[:40]}",
            meeting_date=meeting_date,
            linear_issue=issue,
            title=title,
            task_class="meeting_action",
            sync_notion=False,
        )
        if "notion" in task_class_fan_out("meeting_action"):
            from company_brain.agents.operations.notion.task_sync import TaskSyncAgent
            from company_brain.runtime import get_runtime

            get_runtime().run(
                TaskSyncAgent,
                self.config,
                binding=binding,
                title=title,
                create_if_missing=True,
            )


def extract_action_items(note: dict[str, Any]) -> list[str]:
    """Pull action-item lines from Granola note summary markdown."""
    text = note.get("summary_markdown") or note.get("summary") or note.get("summary_text") or ""
    if not text:
        return []

    items: list[str] = []
    in_actions = False
    for line in str(text).splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("##") and "action" in lower:
            in_actions = True
            continue
        if lower.startswith("##") and in_actions:
            break
        if in_actions and stripped:
            cleaned = _clean_line(stripped)
            if cleaned:
                items.append(cleaned)
            continue
        if any(kw in lower for kw in ACTION_KEYWORDS):
            cleaned = _clean_line(stripped)
            if cleaned:
                items.append(cleaned)
            continue
        if re.match(r"^-\s*\[[ xX]\]", stripped):
            cleaned = _clean_line(stripped)
            if cleaned:
                items.append(cleaned)
    return _dedupe(items)


def _clean_line(line: str) -> str:
    m = ACTION_LINE_RE.match(line)
    body = (m.group(1) if m else line).strip()
    body = re.sub(r"^action items?:\s*", "", body, flags=re.I)
    body = re.sub(r"^todo:\s*", "", body, flags=re.I)
    return body.strip("- ").strip()


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen or len(item) < 4:
            continue
        seen.add(key)
        out.append(item)
    return out
