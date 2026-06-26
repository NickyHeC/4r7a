"""Task database registry and routing from ``config/notion.yaml``."""

from __future__ import annotations

from company_brain.config import NotionConfig, TaskDatabaseSpec, load_notion_config


def resolve_database_key(
    binding_department: str,
    binding_project: str,
    *,
    notion: NotionConfig | None = None,
) -> str | None:
    """Return the configured database key for a binding's department/project."""
    notion = notion or load_notion_config()
    dept = (binding_department or "operations").strip().lower()
    project = (binding_project or "general").strip().lower()

    best_key: str | None = None
    best_score = -1
    for rule in notion.task_routing:
        match = dict(rule.match or {})
        score = 0
        if "department" in match:
            if match["department"].strip().lower() != dept:
                continue
            score += 10
        if "project" in match:
            if match["project"].strip().lower() != project:
                continue
            score += 5
        if score > best_score and rule.database:
            best_score = score
            best_key = rule.database

    if best_key:
        return best_key
    if dept in notion.task_databases:
        return dept
    return None


def resolve_database_spec(
    binding_department: str,
    binding_project: str,
    *,
    notion: NotionConfig | None = None,
) -> tuple[str, TaskDatabaseSpec] | None:
    """Return ``(database_key, spec)`` when configured with a database id."""
    notion = notion or load_notion_config()
    key = resolve_database_key(binding_department, binding_project, notion=notion)
    if not key:
        return None
    spec = notion.task_databases.get(key)
    if spec is None or not (spec.database_id or "").strip():
        return None
    return key, spec


def configured_database_keys(*, notion: NotionConfig | None = None) -> list[str]:
    """Database keys that have a non-empty ``database_id``."""
    notion = notion or load_notion_config()
    out: list[str] = []
    for key, spec in notion.task_databases.items():
        if (spec.database_id or "").strip():
            out.append(key)
    return out
