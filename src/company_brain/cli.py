"""CLI entry point for company-brain."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from company_brain.config import load_config, load_notion_config
from company_brain.notion.client import NotionClient
from company_brain.wiki.index import INDEX_FILENAME, WikiIndex
from company_brain.wiki.registry import REGISTRY_FILENAME, PageRegistry

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def _load_registry() -> PageRegistry:
    registry = PageRegistry(PROJECT_ROOT / REGISTRY_FILENAME)
    registry.load()
    return registry


def _load_index() -> WikiIndex:
    index = WikiIndex(PROJECT_ROOT / INDEX_FILENAME)
    index.load()
    return index


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def main(verbose: bool) -> None:
    """company-brain: company wiki maintenance layer backed by Notion."""
    _setup_logging(verbose)


@main.command()
def init() -> None:
    """Initialize the wiki structure in Notion.

    Scans the workspace for existing content, prompts for a merge strategy,
    then creates the wiki structure accordingly.
    """
    from company_brain.wiki.setup import run_init

    run_init()


@main.command()
@click.argument("source", required=False)
def ingest(source: str | None) -> None:
    """Run an ingestion agent.

    If SOURCE is given, runs only that ingestor. Otherwise runs all registered ones.
    """
    from company_brain.ingestion.pipeline import IngestionPipeline

    config = load_config()
    pipeline = IngestionPipeline(PROJECT_ROOT)

    if not pipeline.registered_sources:
        click.secho("No ingestion sources registered yet.", fg="yellow")
        click.echo("Agents will be added in subsequent phases.")
        return

    entries = pipeline.run(source=source)
    click.echo(f"Ingested {len(entries)} new entries.")


@main.command()
@click.option("--since", type=click.DateTime(), default=None, help="Only absorb entries after this date.")
def absorb(since: datetime | None) -> None:
    """Compile raw entries into wiki articles and publish to Notion."""
    config = load_config()

    if not config.notion.is_initialized:
        click.secho("Wiki not initialized. Run 'company-brain init' first.", fg="red")
        sys.exit(1)

    from company_brain.ingestion.pipeline import IngestionPipeline

    pipeline = IngestionPipeline(PROJECT_ROOT)

    if since:
        entries = pipeline.load_entries_since(since.replace(tzinfo=timezone.utc))
    else:
        entries = pipeline.load_unabsorbed()

    if not entries:
        click.echo("No unabsorbed entries found.")
        return

    click.echo(f"Found {len(entries)} entries to absorb.")
    click.echo("Absorption logic will be implemented with specific agents.")


@main.command()
@click.argument("question")
def query(question: str) -> None:
    """Query the wiki for information."""
    config = load_config()

    if not config.notion.is_initialized:
        click.secho("Wiki not initialized. Run 'company-brain init' first.", fg="red")
        sys.exit(1)

    index = _load_index()
    results = index.search(question)

    if not results:
        click.echo("No matching articles found.")
        return

    click.echo(f"Found {len(results)} relevant articles:")
    for article in results:
        status = "published" if article.is_published else "draft"
        click.echo(f"  [{status}] {article.title} ({article.section}/{article.type})")


@main.command()
def sync() -> None:
    """Sync local registry with Notion workspace state."""
    config = load_config()

    if not config.notion.is_initialized:
        click.secho("Wiki not initialized. Run 'company-brain init' first.", fg="red")
        sys.exit(1)

    client = NotionClient()
    registry = _load_registry()
    index = _load_index()

    click.echo("Syncing with Notion workspace...")

    synced = 0
    for article_id, article in index.articles.items():
        page_id = registry.get_page_id(article_id)
        if page_id:
            try:
                result = client.get_page(page_id, as_json=True)
                if result.json_data:
                    synced += 1
            except Exception:
                click.echo(f"  Warning: page {page_id} for '{article.title}' not accessible")

    click.echo(f"Synced {synced} articles with Notion.")
    registry.save()


@main.command()
def status() -> None:
    """Show wiki statistics."""
    config = load_config()
    index = _load_index()
    registry = _load_registry()

    click.secho("Wiki Status", bold=True)
    click.echo(f"  Initialized: {'yes' if config.notion.is_initialized else 'no'}")
    click.echo()

    stats = index.stats()
    click.echo(f"  Total articles: {stats['total']}")
    click.echo(f"  Published: {stats['published']}")
    click.echo(f"  Stubs: {stats['stubs']}")
    click.echo(f"  Registry mappings: {registry.count}")
    click.echo()

    if stats["by_section"]:
        click.secho("  Articles by section:", bold=True)
        for section, count in sorted(stats["by_section"].items()):
            click.echo(f"    {section}: {count}")
    else:
        click.echo("  No articles yet.")

    click.echo()
    notion_config = load_notion_config()
    if notion_config.discovery.strategy:
        click.echo(f"  Init strategy: {notion_config.discovery.strategy}")
        click.echo(f"  Last scanned: {notion_config.discovery.scanned_at or 'never'}")


@main.command()
def cleanup() -> None:
    """Audit and enrich existing wiki articles."""
    config = load_config()

    if not config.notion.is_initialized:
        click.secho("Wiki not initialized. Run 'company-brain init' first.", fg="red")
        sys.exit(1)

    index = _load_index()
    stats = index.stats()

    click.echo(f"Auditing {stats['total']} articles...")
    click.echo(f"  Stubs needing enrichment: {stats['stubs']}")
    click.echo("Cleanup agents will be implemented in subsequent phases.")
