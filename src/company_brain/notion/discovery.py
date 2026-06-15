"""Workspace discovery: scan existing Notion pages and classify content."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import click

from company_brain.config import WikiConfig
from company_brain.notion.client import NotionClient
from company_brain.wiki.taxonomy import classify_title

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredPage:
    page_id: str
    title: str
    parent_id: str | None
    parent_type: str
    last_edited: str
    url: str = ""
    classified_type: str | None = None
    children_count: int = 0


@dataclass
class DiscoveredDatabase:
    database_id: str
    title: str
    entry_count: int = 0
    properties: list[str] = field(default_factory=list)


@dataclass
class PageGroup:
    """A group of pages under a common top-level parent."""
    label: str
    parent_id: str | None
    pages: list[DiscoveredPage] = field(default_factory=list)
    last_edited: str = ""

    @property
    def count(self) -> int:
        return len(self.pages)


@dataclass
class DiscoveryReport:
    workspace_id: str
    pages: list[DiscoveredPage]
    databases: list[DiscoveredDatabase]
    groups: list[PageGroup]
    total_pages: int
    total_databases: int
    scanned_at: str = ""

    @property
    def has_content(self) -> bool:
        return self.total_pages > 0 or self.total_databases > 0


def scan_workspace(client: NotionClient, wiki_config: WikiConfig) -> DiscoveryReport:
    """Scan the Notion workspace and classify existing content."""
    logger.info("Scanning workspace for existing content...")

    pages_raw = client.search_all_pages()
    databases_raw = client.search_all_databases()

    pages = [_parse_page(p) for p in pages_raw]
    databases = [_parse_database(d) for d in databases_raw]

    for page in pages:
        page.classified_type = classify_title(page.title)

    groups = _group_pages(pages)

    me_result = client.api("v1/users/me")
    workspace_id = ""
    if me_result.json_data and isinstance(me_result.json_data, dict):
        bot = me_result.json_data.get("bot", {})
        workspace_id = bot.get("workspace_name", "")

    return DiscoveryReport(
        workspace_id=workspace_id,
        pages=pages,
        databases=databases,
        groups=groups,
        total_pages=len(pages),
        total_databases=len(databases),
        scanned_at=datetime.now().isoformat(),
    )


def print_report(report: DiscoveryReport) -> None:
    """Print a human-readable discovery report to the terminal."""
    click.echo()
    click.secho(f"Workspace: {report.workspace_id or '(unknown)'}", bold=True)
    click.echo()

    if not report.has_content:
        click.secho("No existing content found. The workspace is empty.", fg="green")
        return

    click.echo(f"Found {report.total_pages} existing pages:")
    for group in report.groups:
        last_edit = f" (last edited {group.last_edited})" if group.last_edited else ""
        click.echo(f"  {group.label:<30} - {group.count} pages{last_edit}")

    if report.databases:
        click.echo()
        click.echo(f"Found {report.total_databases} databases:")
        for db in report.databases:
            click.echo(f"  {db.title:<30} - {db.entry_count} entries")

    click.echo()


def prompt_strategy() -> str:
    """Prompt the user for a merge strategy. Returns one of: adopt, alongside, selective, abort."""
    click.echo("How would you like to proceed?")
    click.echo()
    click.secho("  [1] Adopt     ", fg="cyan", nl=False)
    click.echo("- Import existing pages into the wiki registry (non-destructive)")
    click.secho("  [2] Alongside ", fg="cyan", nl=False)
    click.echo("- Create wiki structure separately, leave existing content alone")
    click.secho("  [3] Selective ", fg="cyan", nl=False)
    click.echo("- Choose which pages to adopt (interactive)")
    click.secho("  [4] Abort     ", fg="cyan", nl=False)
    click.echo("- Exit without making any changes")
    click.echo()

    strategy_map = {"1": "adopt", "2": "alongside", "3": "selective", "4": "abort"}
    while True:
        choice = click.prompt("Enter choice", type=click.Choice(["1", "2", "3", "4"]))
        return strategy_map[choice]


def prompt_selective(groups: list[PageGroup]) -> list[str]:
    """Interactive picker: let user choose which page groups to adopt.

    Returns list of parent page IDs that were selected for adoption.
    """
    click.echo()
    click.secho("Select which sections to adopt into the wiki:", bold=True)
    click.echo()

    adopted_ids: list[str] = []
    for group in groups:
        adopt = click.confirm(f"  Adopt '{group.label}' ({group.count} pages)?", default=False)
        if adopt and group.parent_id:
            adopted_ids.append(group.parent_id)
            for page in group.pages:
                adopted_ids.append(page.page_id)

    return adopted_ids


# -- Internal helpers ---------------------------------------------------------


def _parse_page(raw: dict[str, Any]) -> DiscoveredPage:
    title = _extract_title(raw)
    parent = raw.get("parent", {})
    parent_type = parent.get("type", "workspace")
    parent_id = parent.get(parent_type) if parent_type != "workspace" else None

    return DiscoveredPage(
        page_id=raw.get("id", ""),
        title=title,
        parent_id=parent_id,
        parent_type=parent_type,
        last_edited=raw.get("last_edited_time", ""),
        url=raw.get("url", ""),
    )


def _parse_database(raw: dict[str, Any]) -> DiscoveredDatabase:
    title_parts = raw.get("title", [])
    title = "".join(t.get("plain_text", "") for t in title_parts) if title_parts else "(Untitled)"
    props = list(raw.get("properties", {}).keys())

    return DiscoveredDatabase(
        database_id=raw.get("id", ""),
        title=title,
        properties=props,
    )


def _extract_title(page: dict[str, Any]) -> str:
    props = page.get("properties", {})
    for key in ("title", "Name", "name"):
        prop = props.get(key, {})
        title_arr = prop.get("title", [])
        if title_arr:
            return "".join(t.get("plain_text", "") for t in title_arr)
    return "(Untitled)"


def _group_pages(pages: list[DiscoveredPage]) -> list[PageGroup]:
    """Group pages by their top-level parent."""
    top_level: dict[str | None, PageGroup] = {}
    page_map = {p.page_id: p for p in pages}

    for page in pages:
        if page.parent_type == "workspace" or page.parent_id is None:
            group = top_level.setdefault(
                page.page_id,
                PageGroup(label=page.title, parent_id=page.page_id),
            )
            group.last_edited = max(group.last_edited, page.last_edited)
        else:
            root_id = _find_root(page, page_map)
            root_page = page_map.get(root_id)
            label = root_page.title if root_page else "(ungrouped)"
            group = top_level.setdefault(
                root_id,
                PageGroup(label=label, parent_id=root_id),
            )
            group.pages.append(page)
            group.last_edited = max(group.last_edited, page.last_edited)

    for gid, group in top_level.items():
        root_page = page_map.get(gid) if gid else None
        if root_page and root_page not in group.pages:
            group.pages.insert(0, root_page)

    return sorted(top_level.values(), key=lambda g: g.count, reverse=True)


def _find_root(page: DiscoveredPage, page_map: dict[str, DiscoveredPage]) -> str | None:
    """Walk up the parent chain to find the workspace-level root."""
    visited: set[str] = set()
    current = page
    while current.parent_id and current.parent_id in page_map:
        if current.parent_id in visited:
            break
        visited.add(current.parent_id)
        current = page_map[current.parent_id]
    return current.page_id
