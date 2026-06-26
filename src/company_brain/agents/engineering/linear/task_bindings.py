"""Task binding registry — cross-platform task identity and wiki mirror.

Persists bindings in ``config/task_bindings.json`` and mirrors each task to
``engineering/tasks/{dept}/{project}/{task_id}.md`` plus a rebuilt index.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from company_brain.config import CONFIG_DIR
from company_brain.wiki.publish import write_wiki_page
from company_brain.wiki.store import WikiStore

BINDINGS_FILE = "task_bindings.json"
WIKI_INDEX = "engineering/tasks/_index.md"
WIKI_INDEX_TITLE = "Task Index"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskBinding:
    task_id: str
    origin: dict[str, Any]
    linear: dict[str, Any]
    platforms: dict[str, Any] = field(default_factory=dict)
    status_track: list[dict[str, Any]] = field(default_factory=list)
    follow_up_of: str | None = None
    task_class: str = "inbox_action"
    project: str = "general"
    title: str = ""
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskBinding:
        return cls(
            task_id=data["task_id"],
            origin=dict(data.get("origin") or {}),
            linear=dict(data.get("linear") or {}),
            platforms=dict(data.get("platforms") or {}),
            status_track=[dict(e) for e in (data.get("status_track") or [])],
            follow_up_of=data.get("follow_up_of"),
            task_class=str(data.get("task_class") or "inbox_action"),
            project=str(data.get("project") or "general"),
            title=str(data.get("title") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def department(self) -> str:
        return str(self.origin.get("department") or "operations")


class TaskBindingStore:
    """Atomic JSON store for task bindings."""

    def __init__(self, config_dir: Path | None = None):
        self._path = (config_dir or CONFIG_DIR) / BINDINGS_FILE

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"version": 1, "tasks": {}}
        try:
            data = json.loads(self._path.read_text()) or {}
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "tasks": {}}
        data.setdefault("version", 1)
        data.setdefault("tasks", {})
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.replace(self._path)

    def list_all(self) -> list[TaskBinding]:
        tasks = self._load().get("tasks") or {}
        return [TaskBinding.from_dict(v) for v in tasks.values()]

    def get(self, task_id: str) -> TaskBinding | None:
        raw = (self._load().get("tasks") or {}).get(task_id)
        if not raw:
            return None
        return TaskBinding.from_dict(raw)

    def upsert(
        self,
        binding: TaskBinding,
        *,
        mirror_wiki: bool = True,
        wiki_store: WikiStore | None = None,
        sync_notion: bool = True,
    ) -> TaskBinding:
        data = self._load()
        now = _utc_now()
        if not binding.created_at:
            binding.created_at = now
        binding.updated_at = now
        data["tasks"][binding.task_id] = binding.to_dict()
        self._save(data)
        if mirror_wiki:
            mirror_binding_to_wiki(binding, store=wiki_store, sync=sync_notion)
            rebuild_task_index(self.list_all(), store=wiki_store, sync=sync_notion)
        return binding

    def find_by_linear(self, issue_ref: str) -> TaskBinding | None:
        ref = (issue_ref or "").strip()
        if not ref:
            return None
        for binding in self.list_all():
            linear = binding.linear
            if linear.get("issue_id") == ref or linear.get("identifier") == ref:
                return binding
        return None

    def find_by_gmail_message(self, message_id: str) -> TaskBinding | None:
        mid = (message_id or "").strip()
        if not mid:
            return None
        for binding in self.list_all():
            gmail = binding.platforms.get("gmail") or {}
            if gmail.get("message_id") == mid:
                return binding
        return None

    def find_by_notion_page(self, page_id: str) -> TaskBinding | None:
        pid = (page_id or "").strip()
        if not pid:
            return None
        for binding in self.list_all():
            notion = binding.platforms.get("notion") or {}
            if notion.get("page_id") == pid:
                return binding
        return None

    def create_gmail_binding(
        self,
        *,
        message_id: str,
        thread_id: str,
        mailbox: str,
        linear_issue: dict[str, Any],
        title: str,
        task_class: str = "inbox_action",
        department: str = "operations",
        project: str = "general",
        mirror_wiki: bool = True,
        wiki_store: WikiStore | None = None,
        sync_notion: bool = True,
    ) -> TaskBinding:
        existing = self.find_by_gmail_message(message_id)
        if existing:
            existing.linear = {
                "issue_id": linear_issue.get("id", ""),
                "identifier": linear_issue.get("identifier", ""),
                "url": linear_issue.get("url", ""),
            }
            existing.title = title or existing.title
            existing.platforms.setdefault("gmail", {})
            existing.platforms["gmail"].update({
                "message_id": message_id,
                "thread_id": thread_id,
                "mailbox": mailbox,
                "archived": existing.platforms.get("gmail", {}).get("archived", False),
            })
            return self.upsert(
                existing,
                mirror_wiki=mirror_wiki,
                wiki_store=wiki_store,
                sync_notion=sync_notion,
            )

        task_id = str(uuid.uuid4())
        binding = TaskBinding(
            task_id=task_id,
            origin={
                "platform": "gmail",
                "artifact_id": message_id,
                "department": department,
            },
            linear={
                "issue_id": linear_issue.get("id", ""),
                "identifier": linear_issue.get("identifier", ""),
                "url": linear_issue.get("url", ""),
            },
            platforms={
                "gmail": {
                    "message_id": message_id,
                    "thread_id": thread_id,
                    "mailbox": mailbox,
                    "archived": False,
                },
            },
            task_class=task_class,
            project=project,
            title=title,
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        return self.upsert(
            binding,
            mirror_wiki=mirror_wiki,
            wiki_store=wiki_store,
            sync_notion=sync_notion,
        )

    def find_by_granola_note(self, note_id: str) -> TaskBinding | None:
        nid = (note_id or "").strip()
        if not nid:
            return None
        for binding in self.list_all():
            granola = binding.platforms.get("granola") or {}
            if granola.get("note_id") == nid:
                return binding
        return None

    def create_granola_binding(
        self,
        *,
        note_id: str,
        meeting_date: str,
        linear_issue: dict[str, Any],
        title: str,
        task_class: str = "meeting_action",
        department: str = "operations",
        project: str = "general",
        mirror_wiki: bool = True,
        wiki_store: WikiStore | None = None,
        sync_notion: bool = True,
    ) -> TaskBinding:
        task_id = str(uuid.uuid4())
        binding = TaskBinding(
            task_id=task_id,
            origin={
                "platform": "granola",
                "artifact_id": note_id,
                "department": department,
            },
            linear={
                "issue_id": linear_issue.get("id", ""),
                "identifier": linear_issue.get("identifier", ""),
                "url": linear_issue.get("url", ""),
            },
            platforms={
                "granola": {
                    "note_id": note_id,
                    "meeting_date": meeting_date,
                },
            },
            task_class=task_class,
            project=project,
            title=title,
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        return self.upsert(
            binding,
            mirror_wiki=mirror_wiki,
            wiki_store=wiki_store,
            sync_notion=sync_notion,
        )

    def find_by_slack_thread(self, channel: str, thread_ts: str) -> TaskBinding | None:
        key = f"{(channel or '').strip()}:{(thread_ts or '').strip()}"
        if key == ":":
            return None
        for binding in self.list_all():
            slack = binding.platforms.get("slack") or {}
            thread_key = f"{slack.get('channel', '')}:{slack.get('thread_ts', '')}"
            if thread_key == key:
                return binding
        return None

    def create_slack_binding(
        self,
        *,
        channel: str,
        thread_ts: str,
        message_ts: str,
        linear_issue: dict[str, Any],
        title: str,
        task_class: str = "slack_action",
        department: str = "operations",
        project: str = "general",
        mirror_wiki: bool = True,
        wiki_store: WikiStore | None = None,
        sync_notion: bool = True,
    ) -> TaskBinding:
        existing = self.find_by_slack_thread(channel, thread_ts)
        if existing:
            existing.linear = {
                "issue_id": linear_issue.get("id", ""),
                "identifier": linear_issue.get("identifier", ""),
                "url": linear_issue.get("url", ""),
            }
            existing.title = title or existing.title
            existing.platforms.setdefault("slack", {})
            existing.platforms["slack"].update({
                "channel": channel,
                "thread_ts": thread_ts,
                "message_ts": message_ts,
                "replied": existing.platforms.get("slack", {}).get("replied", False),
            })
            return self.upsert(
                existing,
                mirror_wiki=mirror_wiki,
                wiki_store=wiki_store,
                sync_notion=sync_notion,
            )

        artifact = f"{channel}:{thread_ts}:{message_ts}"
        binding = TaskBinding(
            task_id=str(uuid.uuid4()),
            origin={
                "platform": "slack",
                "artifact_id": artifact,
                "department": department,
            },
            linear={
                "issue_id": linear_issue.get("id", ""),
                "identifier": linear_issue.get("identifier", ""),
                "url": linear_issue.get("url", ""),
            },
            platforms={
                "slack": {
                    "channel": channel,
                    "thread_ts": thread_ts,
                    "message_ts": message_ts,
                    "replied": False,
                },
            },
            task_class=task_class,
            project=project,
            title=title,
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        return self.upsert(
            binding,
            mirror_wiki=mirror_wiki,
            wiki_store=wiki_store,
            sync_notion=sync_notion,
        )


def mirror_binding_to_wiki(
    binding: TaskBinding,
    *,
    store: WikiStore | None = None,
    sync: bool = True,
) -> None:
    """Write or update the per-task wiki detail page."""
    rel = task_detail_path(binding)
    body = _render_detail_body(binding)
    write_wiki_page(
        rel,
        binding.title or f"Task {binding.task_id[:8]}",
        body,
        mode="update",
        section="engineering/tasks",
        store=store,
        sync=sync,
    )


def rebuild_task_index(
    bindings: Iterable[TaskBinding],
    *,
    store: WikiStore | None = None,
    sync: bool = True,
) -> None:
    """Rebuild ``engineering/tasks/_index.md`` from all bindings."""
    grouped: dict[str, dict[str, list[TaskBinding]]] = {}
    for b in bindings:
        grouped.setdefault(b.department, {}).setdefault(b.project, []).append(b)

    lines = ["# Task Index", ""]
    if not grouped:
        lines.append("_No tasks bound yet._")
    for dept in sorted(grouped):
        lines.append(f"## {dept.title()}")
        lines.append("")
        for project in sorted(grouped[dept]):
            lines.append(f"### {project}")
            lines.append("")
            for b in sorted(grouped[dept][project], key=lambda x: x.updated_at, reverse=True):
                ident = b.linear.get("identifier") or b.task_id[:8]
                detail = task_detail_path(b)
                notion = b.platforms.get("notion") or {}
                notion_hint = " · Notion" if notion.get("page_id") else ""
                lines.append(
                    f"- [[{ident}|{detail}]] — {b.title or '(untitled)'}{notion_hint}"
                )
            lines.append("")

    write_wiki_page(
        WIKI_INDEX,
        WIKI_INDEX_TITLE,
        "\n".join(lines).rstrip() + "\n",
        mode="update",
        section="engineering/tasks",
        store=store,
        sync=sync,
    )


def task_detail_path(binding: TaskBinding) -> str:
    dept = _slug(binding.department)
    project = _slug(binding.project)
    return f"engineering/tasks/{dept}/{project}/{binding.task_id}.md"


def _slug(value: str) -> str:
    out = "".join(c if c.isalnum() or c in "-_" else "-" for c in value.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "general"


def _render_detail_body(binding: TaskBinding) -> str:
    lines = [
        f"# {binding.title or 'Task'}",
        "",
        f"- **Task ID:** `{binding.task_id}`",
        f"- **Class:** {binding.task_class}",
        f"- **Origin:** {binding.origin.get('platform', '?')} / {binding.department}",
    ]
    if binding.follow_up_of:
        lines.append(f"- **Follow-up of:** `{binding.follow_up_of}`")
    ident = binding.linear.get("identifier")
    url = binding.linear.get("url")
    if ident:
        if url:
            lines.append(f"- **Linear:** [{ident}]({url})")
        else:
            lines.append(f"- **Linear:** {ident}")

    notion = binding.platforms.get("notion") or {}
    notion_url = notion.get("url")
    notion_page = notion.get("page_id")
    if notion_url:
        label = notion.get("database_key") or "Notion task"
        lines.append(f"- **Notion:** [{label}]({notion_url})")
    elif notion_page:
        db_key = notion.get("database_key") or "task"
        lines.append(f"- **Notion:** `{db_key}` row `{notion_page}`")

    if binding.platforms:
        lines.extend(["", "## Platforms", ""])
        for platform, data in sorted(binding.platforms.items()):
            lines.append(f"### {platform.title()}")
            lines.append("")
            for key, val in sorted(data.items()):
                lines.append(f"- **{key.replace('_', ' ').title()}:** `{val}`")
            lines.append("")

    if binding.status_track:
        lines.extend([
            "",
            "## Status track",
            "",
            "| Platform | Field | Value | Updated |",
            "|---|---|---|---|",
        ])
        for entry in binding.status_track:
            lines.append(
                f"| {entry.get('platform', '')} | {entry.get('field', '')} "
                f"| {entry.get('value', '')} | {entry.get('updated_at', '')} |"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def attach_notion_platform(
    binding: TaskBinding,
    *,
    database_key: str,
    page_id: str,
    url: str = "",
    title: str | None = None,
) -> TaskBinding:
    """Attach or update Notion database row metadata on a binding."""
    binding.platforms.setdefault("notion", {})
    binding.platforms["notion"].update({
        "database_key": database_key,
        "page_id": page_id,
        "url": url,
    })
    if title:
        binding.title = title
    return binding
