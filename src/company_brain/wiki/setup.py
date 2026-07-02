"""Wiki setup: initializes the Notion wiki structure.

Orchestrates the full init flow:
1. Verify ntn is installed and authenticated
2. Run workspace discovery
3. Prompt user for merge strategy
4. Execute the chosen strategy
5. Write config/notion.yaml and registry
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from company_brain.config import (
    DiscoveryState,
    load_config,
    load_notion_config,
    save_notion_config,
)
from company_brain.notion.client import NotionClient
from company_brain.notion.discovery import (
    DiscoveryReport,
    print_report,
    prompt_selective,
    prompt_strategy,
    scan_workspace,
)
from company_brain.output.formatter import format_section_page
from company_brain.wiki.registry import REGISTRY_FILENAME, PageRegistry
from company_brain.wiki.taxonomy import classify_title, get_section_for_article_type

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def run_init() -> None:
    """Main init entry point."""
    config = load_config()
    client = NotionClient()

    if not client.is_installed():
        click.secho("Error: 'ntn' CLI not found on PATH.", fg="red")
        click.echo("Install it: curl -fsSL https://ntn.dev | bash")
        sys.exit(1)

    if not client.check_auth():
        click.secho("Error: 'ntn' is not authenticated.", fg="red")
        click.echo("Run: ntn login")
        sys.exit(1)

    click.secho("Connected to Notion workspace.", fg="green")

    report = scan_workspace(client, config.wiki)
    print_report(report)

    if report.has_content:
        strategy = prompt_strategy()
    else:
        strategy = "fresh"
        click.echo("Proceeding with fresh wiki setup.")

    if strategy == "abort":
        click.echo("Aborted. No changes made.")
        sys.exit(0)

    notion_config = load_notion_config()
    registry = PageRegistry(PROJECT_ROOT / REGISTRY_FILENAME)
    registry.load()

    if strategy == "adopt":
        _execute_adopt(client, config, report, notion_config, registry)
    elif strategy == "selective":
        _execute_selective(client, config, report, notion_config, registry)
    elif strategy in ("alongside", "fresh"):
        _execute_alongside(client, config, notion_config, registry)

    notion_config.discovery = DiscoveryState(
        strategy=strategy,
        scanned_at=report.scanned_at,
        existing_page_count=report.total_pages,
        adopted_page_ids=[p.page_id for p in report.pages] if strategy == "adopt" else [],
    )

    save_notion_config(notion_config)
    registry.save()

    click.echo()
    click.secho("Wiki initialization complete!", fg="green", bold=True)
    click.echo(f"  Root page ID: {notion_config.root_page_id}")
    click.echo(f"  Sections created: {len(notion_config.section_page_ids)}")
    click.echo(f"  Registry entries: {registry.count}")


def _execute_adopt(
    client: NotionClient,
    config,
    report: DiscoveryReport,
    notion_config,
    registry: PageRegistry,
) -> None:
    click.echo()
    click.secho("Adopting existing pages...", bold=True)

    root_page_id = _find_or_create_root(client, config, notion_config)

    for page in report.pages:
        article_type = page.classified_type or classify_title(page.title)
        if article_type:
            section = get_section_for_article_type(article_type, config.wiki)
            if section:
                registry.register(page.page_id, page.page_id)
                click.echo(f"  Adopted: {page.title} -> {section}/{article_type}")

    _create_missing_sections(client, config, root_page_id, notion_config, registry)


def _execute_selective(
    client: NotionClient,
    config,
    report: DiscoveryReport,
    notion_config,
    registry: PageRegistry,
) -> None:
    adopted_ids = prompt_selective(report.groups)

    root_page_id = _find_or_create_root(client, config, notion_config)

    for page in report.pages:
        if page.page_id in adopted_ids:
            registry.register(page.page_id, page.page_id)
            click.echo(f"  Adopted: {page.title}")

    _create_missing_sections(client, config, root_page_id, notion_config, registry)


def _execute_alongside(
    client: NotionClient,
    config,
    notion_config,
    registry: PageRegistry,
) -> None:
    click.echo()
    click.secho("Creating wiki structure...", bold=True)

    root_page_id = _find_or_create_root(client, config, notion_config)
    _create_all_sections(client, config, root_page_id, notion_config, registry)


def _find_or_create_root(client: NotionClient, config, notion_config) -> str:
    if notion_config.root_page_id:
        return notion_config.root_page_id

    wiki_name = config.wiki.wiki_name

    parent_id = click.prompt(
        "Enter the Notion page ID to create the wiki under (or 'workspace' for top-level)",
        default="workspace",
    )

    click.echo(f"  Creating root page: {wiki_name}")

    markdown = (
        f"# {wiki_name}\n\n"
        "The central knowledge base for the company.\n\n"
        "---\n\n"
        "*Navigate to a section below to find articles.*"
    )

    if parent_id == "workspace":
        result = client.api(
            "v1/pages",
            method="POST",
            data=(
                f'{{"parent":{{"type":"workspace","workspace":true}},'
                f'"properties":{{"title":{{"title":[{{"text":{{"content":'
                f'"{_escape_json(wiki_name)}"}}}}]}}}},'
                f'"markdown":"{_escape_json(markdown)}"}}'
            ),
        )
    else:
        result = client.create_page(parent_id, markdown, title=wiki_name)

    page_id = ""
    if result.json_data and isinstance(result.json_data, dict):
        page_id = result.json_data.get("id", "")

    notion_config.root_page_id = page_id
    click.echo(f"  Root page created: {page_id}")
    return page_id


def _create_all_sections(
    client: NotionClient, config, root_page_id: str, notion_config, registry: PageRegistry
) -> None:
    for key, section in config.wiki.sections.items():
        if key in notion_config.section_page_ids:
            continue
        _create_section_page(client, key, section, root_page_id, notion_config, registry)


def _create_missing_sections(
    client: NotionClient, config, root_page_id: str, notion_config, registry: PageRegistry
) -> None:
    for key, section in config.wiki.sections.items():
        if key in notion_config.section_page_ids:
            continue
        if registry.get_section_page_id(key):
            continue
        _create_section_page(client, key, section, root_page_id, notion_config, registry)


def _create_section_page(
    client: NotionClient, key: str, section, root_page_id: str, notion_config, registry
) -> None:
    markdown = format_section_page(section.label, section.description, icon=section.icon)
    click.echo(f"  Creating section: {section.icon} {section.label}")

    result = client.create_page(root_page_id, markdown, title=section.label)
    page_id = ""
    if result.json_data and isinstance(result.json_data, dict):
        page_id = result.json_data.get("id", "")

    if page_id:
        notion_config.section_page_ids[key] = page_id
        registry.register_section(key, page_id)


def _escape_json(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
