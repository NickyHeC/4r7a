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
    result = ContentCatalogAgent(config).run()
    click.echo(
        f"Catalog rebuilt at {result['path']} "
        f"({result['company_pages']} company, {result['external_pages']} external pages)."
    )


@main.group(invoke_without_command=True)
@click.pass_context
@click.option("--json", "as_json", is_flag=True, help="Emit JSON report.")
@click.option("--min-score", type=int, default=None, help="Exit 1 if aggregate score is below N.")
@click.option("--no-history", is_flag=True, help="Skip appending config/doctor-history.json.")
def doctor(ctx: click.Context, as_json: bool, min_score: int | None, no_history: bool) -> None:
    """Diagnose company-brain health (connectivity, agents, wiki, ops).

    Run ``company-brain doctor all`` for the full registry, or a single doctor:
    ``connect``, ``agents``, ``wiki``, ``ops``.
    """
    if ctx.invoked_subcommand is None:
        from company_brain.doctor.runner import main_exit

        main_exit(
            None,
            as_json=as_json,
            min_score=min_score,
            record_history=not no_history,
        )


def _doctor_options(fn):
    fn = click.option("--json", "as_json", is_flag=True)(fn)
    fn = click.option("--min-score", type=int, default=None)(fn)
    fn = click.option("--no-history", is_flag=True)(fn)
    return fn


@doctor.command("connect")
@_doctor_options
def doctor_connect(as_json: bool, min_score: int | None, no_history: bool) -> None:
    """Platform connectivity and env tokens."""
    from company_brain.doctor.runner import main_exit

    main_exit(
        ["connect"],
        as_json=as_json,
        min_score=min_score,
        record_history=not no_history,
    )


@doctor.command("agents")
@_doctor_options
def doctor_agents(as_json: bool, min_score: int | None, no_history: bool) -> None:
    """Agent naming, docs, Smolfile allow_hosts, handbook coverage."""
    from company_brain.doctor.runner import main_exit

    main_exit(
        ["agents"],
        as_json=as_json,
        min_score=min_score,
        record_history=not no_history,
    )


@doctor.command("wiki")
@_doctor_options
def doctor_wiki(as_json: bool, min_score: int | None, no_history: bool) -> None:
    """Wiki MD-first / Notion mirror invariants."""
    from company_brain.doctor.runner import main_exit

    main_exit(
        ["wiki"],
        as_json=as_json,
        min_score=min_score,
        record_history=not no_history,
    )


@doctor.command("ops")
@_doctor_options
def doctor_ops(as_json: bool, min_score: int | None, no_history: bool) -> None:
    """Slack notifier, Gmail actuation, receipt forwarding policy."""
    from company_brain.doctor.runner import main_exit

    main_exit(
        ["ops"],
        as_json=as_json,
        min_score=min_score,
        record_history=not no_history,
    )


@doctor.command("naming")
@_doctor_options
def doctor_naming(as_json: bool, min_score: int | None, no_history: bool) -> None:
    """Naming doctor — agent filenames, wiki slugs, legacy path drift."""
    from company_brain.doctor.runner import main_exit

    main_exit(
        ["naming"],
        as_json=as_json,
        min_score=min_score,
        record_history=not no_history,
    )


@doctor.command("llm")
@_doctor_options
def doctor_llm(as_json: bool, min_score: int | None, no_history: bool) -> None:
    """LLM doctor — tier bindings, budget, model health + auto-fallback."""
    from company_brain.doctor.runner import main_exit

    main_exit(
        ["llm"],
        as_json=as_json,
        min_score=min_score,
        record_history=not no_history,
    )


@main.group()
def crm() -> None:
    """CRM entity registry and wiki structure."""


@crm.command("seed")
def crm_seed() -> None:
    """Create CRM wiki folders, indexes, and promotion log if missing."""
    from company_brain.crm.registry import rebuild_registry
    from company_brain.crm.seeds import ensure_crm_seeds

    created = ensure_crm_seeds()
    registry = rebuild_registry()
    click.secho(
        f"CRM seeds: {created} path(s) created; registry has "
        f"{len(registry.by_email)} email(s), {len(registry.by_domain)} domain(s).",
        fg="green",
    )


@crm.command("rebuild-registry")
def crm_rebuild_registry() -> None:
    """Rebuild crm/_registry.json from contact pages and segment indexes."""
    from company_brain.crm.registry import rebuild_registry

    registry = rebuild_registry()
    click.echo(
        f"Registry rebuilt: {len(registry.by_email)} email(s), "
        f"{len(registry.by_domain)} domain(s) (updated {registry.updated_at})."
    )


@crm.command("sync-notion")
@click.option("--force", is_flag=True, help="Re-sync even when content hash unchanged.")
def crm_sync_notion(force: bool) -> None:
    """Mirror CRM contact and inbound pages to configured Notion databases."""
    from company_brain.crm.notion_sync import configured_crm_database_keys, sync_all_crm

    keys = configured_crm_database_keys()
    if not keys:
        click.secho(
            "No CRM Notion databases configured (set database_id in config/notion.yaml).",
            fg="yellow",
        )
        return

    if force:
        from company_brain.config import resolve_wiki_dir
        from company_brain.crm.notion_sync import crm_database_key_for_rel_path, sync_crm_doc
        from company_brain.wiki.store import LocalWikiStore

        store = LocalWikiStore(root=resolve_wiki_dir())
        results: dict[str, str] = {}
        for rel_path in store.list():
            if not crm_database_key_for_rel_path(rel_path):
                continue
            page_id = sync_crm_doc(rel_path, store=store, force=True)
            if page_id:
                results[rel_path] = page_id
    else:
        results = sync_all_crm()

    click.secho(f"CRM Notion sync: {len(results)} page(s) mirrored.", fg="green")
    for rel, page_id in sorted(results.items()):
        click.echo(f"  {rel} -> {page_id}")


@main.group()
def models() -> None:
    """Configure LLM tiers and onboarding mode."""


@models.command("configure")
@click.option(
    "--mode",
    type=click.Choice(["performance", "balanced"]),
    default=None,
    help="performance = reasoning tier everywhere; balanced = per-agent tiers",
)
def models_configure(mode: str | None) -> None:
    """Write config/models.yaml from onboarding mode choice."""
    from company_brain.llm.setup import apply_mode, prompt_configure

    if mode:
        apply_mode(mode)
        click.secho(f"Wrote config/models.yaml (mode={mode})", fg="green")
    else:
        prompt_configure()


@doctor.command("code")
@_doctor_options
def doctor_code(as_json: bool, min_score: int | None, no_history: bool) -> None:
    """Deterministic code checks (agents, wiki, ops, naming) — no env tokens required."""
    from company_brain.doctor.runner import main_exit

    main_exit(
        ["agents", "wiki", "ops", "naming"],
        as_json=as_json,
        min_score=min_score,
        record_history=not no_history,
    )


@doctor.command("all")
@_doctor_options
def doctor_all(as_json: bool, min_score: int | None, no_history: bool) -> None:
    """Run every doctor in the registry."""
    from company_brain.doctor.runner import main_exit

    main_exit(
        None,
        as_json=as_json,
        min_score=min_score,
        record_history=not no_history,
    )
