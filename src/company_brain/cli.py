"""CLI entry point for company-brain."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from company_brain.config import (
    load_config,
    load_notion_config,
    resolve_wiki_dir,
)
from company_brain.wiki.index import WikiIndex
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
    index = WikiIndex()
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

    pipeline = IngestionPipeline()

    if not pipeline.registered_sources:
        click.secho("No ingestion sources registered yet.", fg="yellow")
        click.echo("Agents will be added in subsequent phases.")
        return

    entries = pipeline.run(source=source)
    click.echo(f"Ingested {len(entries)} new entries to raw/entries/ (Markdown).")


@main.command()
@click.option(
    "--since", type=click.DateTime(), default=None, help="Only absorb entries after this date."
)
@click.option("--model", default=None, help="Override the model for the absorb writer.")
def absorb(since: datetime | None, model: str | None) -> None:
    """Compile raw entries into wiki articles (MD source of truth) and sync to Notion."""
    from company_brain.wiki.absorb import AbsorbWriter

    since_dt = since.replace(tzinfo=timezone.utc) if since else None
    writer = AbsorbWriter(model=model)
    click.echo("Absorbing raw entries into the wiki (Markdown first, then Notion sync)...")
    result = writer.run(since=since_dt)
    if not result.get("absorbed"):
        click.echo("No unabsorbed entries found.")
        return
    click.echo(
        f"Absorbed {result['absorbed']} entries across {result['batches']} batch(es); "
        f"synced {result.get('synced', 0)} page(s) to Notion."
    )


@main.command("query")
@click.argument("question")
@click.option(
    "--as-member",
    default="",
    help="Member key for query_grants (omit / admin → admin bypass)",
)
@click.option("--expand", default="", help="Expand one result by wiki rel_path")
@click.option("--limit", default=8, show_default=True, type=int)
@click.option("--no-company", is_flag=True, help="Search employee scopes only")
def query(
    question: str,
    as_member: str,
    expand: str,
    limit: int,
    no_company: bool,
) -> None:
    """Citation-only Query (snippets + Notion cite; grant-aware)."""
    from company_brain.wiki.citation_query import (
        citation_query,
        expand_result,
        format_cli_results,
    )

    if expand:
        out = expand_result(expand, as_member=as_member)
        if out.get("status") != "ok":
            click.secho(f"Expand failed: {out}", fg="red")
            sys.exit(1)
        click.echo(f"# {out.get('title')}")
        click.echo(f"cite: {out.get('citation')}")
        click.echo(f"path: {out.get('rel_path')} [{out.get('volume')}]")
        click.echo()
        click.echo(out.get("body") or "")
        return

    result = citation_query(
        question,
        as_member=as_member,
        limit=limit,
        include_company=not no_company,
    )
    click.echo(format_cli_results(result))


@main.command()
def sync() -> None:
    """Push changed wiki Markdown pages to Notion (MD is the source of truth)."""
    config = load_config()

    if not config.notion.is_initialized:
        click.secho("Wiki not initialized. Run 'company-brain init' first.", fg="red")
        sys.exit(1)

    from company_brain.notion.sync import NotionSync

    click.echo("Syncing wiki Markdown -> Notion...")
    synced = NotionSync(config=config).sync_all()
    click.echo(f"Synced {len(synced)} page(s) to Notion.")


@main.command()
def status() -> None:
    """Show wiki statistics."""
    config = load_config()
    index = _load_index()
    registry = _load_registry()

    click.secho("Wiki Status", bold=True)
    click.echo(f"  Initialized: {'yes' if config.notion.is_initialized else 'no'}")
    click.echo(f"  Wiki dir: {resolve_wiki_dir()}")
    click.echo()

    stats = index.stats()
    click.echo(f"  Total articles (Markdown): {stats['total']}")
    click.echo(f"  Synced to Notion: {stats['published']}")
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


@main.command("migrate-names")
@click.option("--apply", is_flag=True, help="Apply changes (default is dry-run preview).")
@click.option("--company/--no-company", default=True, help="Scan the company wiki volume.")
@click.option("--employee/--no-employee", default=True, help="Scan the employee wiki volume.")
@click.option("--routing/--no-routing", default=True, help="Migrate Gmail routing handled keys.")
@click.option(
    "--gate-keys/--no-gate-keys",
    default=True,
    help="Migrate config/state.json handled + scanner keys after agent renames.",
)
@click.option(
    "--rebuild-index",
    is_flag=True,
    help="Rebuild company wiki _index.md and _backlinks.json after apply.",
)
def migrate_names(
    apply: bool,
    company: bool,
    employee: bool,
    routing: bool,
    gate_keys: bool,
    rebuild_index: bool,
) -> None:
    """Rename legacy wiki paths/titles to naming-convention slugs.

    Dry-run by default. Use on existing wiki trees or before syncing imported
    Markdown that uses pre-migration paths (open-prs, expense-reports/, etc.).
    """
    from company_brain.config import resolve_employee_wiki_dir, resolve_wiki_dir
    from company_brain.wiki.employee_store import LocalEmployeeWikiStore
    from company_brain.wiki.name_migrate import apply_migration, plan_migration
    from company_brain.wiki.store import LocalWikiStore

    company_store = LocalWikiStore(root=resolve_wiki_dir()) if company else None
    employee_store = LocalEmployeeWikiStore(root=resolve_employee_wiki_dir()) if employee else None

    plan = plan_migration(
        company_store=company_store,
        employee_store=employee_store,
        include_routing=routing,
        rewrite_links=True,
    )

    if not plan.renames and not plan.routing_updates:
        if gate_keys:
            click.echo("No legacy wiki paths or routing keys; gate-key migration only.")
        else:
            click.echo("No legacy paths or routing keys to migrate.")
            if plan.conflicts:
                for msg in plan.conflicts:
                    click.secho(f"  conflict: {msg}", fg="yellow")
            return

    click.secho("Migration plan", bold=True)
    for rename in plan.renames:
        click.echo(f"  [{rename.volume}] {rename.old_path} -> {rename.new_path}")
    for upd in plan.routing_updates:
        click.echo(f"  [routing] {upd.rel_path}: {upd.old_key} -> {upd.new_key}")
    if plan.link_rewrites:
        click.echo(f"  link/title touch: {len(plan.link_rewrites)} page(s)")
    for msg in plan.conflicts:
        click.secho(f"  conflict (skipped): {msg}", fg="yellow")

    if not apply:
        click.echo()
        if gate_keys:
            click.echo("  [gate-keys] config/state.json handled + scanner prefixes")
        click.secho("Dry run — re-run with --apply to execute.", fg="yellow")
        return

    counts = {"renamed": 0, "titles": 0, "routing": 0}
    if plan.renames or plan.routing_updates:
        counts = apply_migration(
            plan,
            company_store=company_store,
            employee_store=employee_store,
            rebuild_index=rebuild_index,
        )
    gate_counts = {"handled": 0, "state": 0}
    if gate_keys and apply:
        from company_brain.agents.gates import migrate_gate_keys

        gate_counts = migrate_gate_keys()
    click.secho(
        f"Applied: {counts['renamed']} renamed, {counts['titles']} page(s) updated, "
        f"{counts['routing']} routing record(s) patched, "
        f"{gate_counts['handled']} gate handled key(s), {gate_counts['state']} state key(s).",
        fg="green",
    )


@main.command()
def catalog() -> None:
    """Rebuild the admin content table of contents (``admin/content-catalog.md``)."""
    from company_brain.agents.external_wiki.content_catalog import ContentCatalogAgent

    config = load_config()
    result = ContentCatalogAgent(config).execute()
    click.echo(
        f"Catalog rebuilt at {result['path']} "
        f"({result['company_pages']} company, {result['external_pages']} external pages)."
    )


def _register_commands() -> None:
    from company_brain.cli_commands import (
        admin,
        collaboration,
        doctor,
        people_platforms,
        product_growth,
        system,
    )

    for command_module in (doctor, system, collaboration, admin, product_growth, people_platforms):
        command_module.register(main)


_register_commands()
