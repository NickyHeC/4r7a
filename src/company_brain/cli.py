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


@models.command("budget")
@click.option("--month", default=None, help="Month to report (YYYY-MM). Default: current.")
@click.option(
    "--reconcile",
    is_flag=True,
    help="Compare tracked usage to Mercury LLM vendor bills.",
)
def models_budget(month: str | None, reconcile: bool) -> None:
    """Show LLM token budget status and per-agent run caps."""
    from company_brain.llm.budget import budget_status, resolve_run_limits
    from company_brain.llm.reconcile import format_reconciliation, reconciliation_report
    from company_brain.llm.tiers import LLM_AGENTS

    status = budget_status()
    if status["enabled"]:
        click.echo(
            f"Budget {status['month']}: ${status['spent_usd']:.2f} / ${status['limit_usd']:.2f} "
            f"({status['percent_used']}%)"
        )
        click.echo(
            f"  runtime ${status['runtime_usd']:.2f}, builder ${status['builder_usd']:.2f} "
            f"(guidance ${status.get('guidance_usd', {}).get('runtime', 0):.0f} / "
            f"${status.get('guidance_usd', {}).get('builder', 0):.0f})"
        )
        in_tok = int(status["input_tokens"])
        out_tok = int(status["output_tokens"])
        click.echo(f"  tokens in/out: {in_tok:,} / {out_tok:,}")
    else:
        click.secho(
            "Token budget disabled (set token_budget.enabled in config/models.yaml)",
            fg="yellow",
        )

    click.echo("\nPer-agent run caps:")
    for agent in sorted(LLM_AGENTS):
        limits = resolve_run_limits(agent)
        bits = []
        if limits.max_usd_per_run is not None:
            bits.append(f"${limits.max_usd_per_run:.2f}/run")
        if limits.max_steps_per_run is not None:
            bits.append(f"{limits.max_steps_per_run} steps")
        if limits.max_tool_calls_per_run is not None:
            bits.append(f"{limits.max_tool_calls_per_run} tools")
        click.echo(f"  {agent}: {', '.join(bits) if bits else '(defaults)'}")

    if reconcile or month:
        report = reconciliation_report(month=month)
        click.echo("")
        if report["warn"]:
            click.secho(format_reconciliation(report), fg="yellow")
        else:
            click.echo(format_reconciliation(report))


@models.command("spot-check")
@click.option(
    "--agent",
    "agents",
    multiple=True,
    help="Run spot check for one agent (repeatable). Default: all configured agents.",
)
@click.option("--dry-run", is_flag=True, help="Run fixtures but do not post to Slack.")
def models_spot_check(agents: tuple[str, ...], dry_run: bool) -> None:
    """Run LLM vibe-eval spot checks and post samples to #wiki for human review."""
    from company_brain.llm.spot_check import run_all_spot_checks, run_spot_check, spot_check_config

    cfg = spot_check_config()
    if not cfg.get("enabled", True):
        click.secho("eval_spotcheck.enabled is false in config/models.yaml.", fg="yellow")
        return
    names = list(agents) if agents else None
    if dry_run:
        for name in names or cfg.get("agents") or []:
            result = run_spot_check(name)
            if result.error:
                click.secho(f"{name}: {result.error}", fg="red")
            else:
                click.echo(f"{name}: {len(result.output)} chars output")
        return
    results = run_all_spot_checks(names, post=True)
    click.echo(f"Posted {len(results)} spot check(s) to {cfg.get('channel', '#wiki')}.")


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


@doctor.command("bridge")
@_doctor_options
def doctor_bridge(as_json: bool, min_score: int | None, no_history: bool) -> None:
    """Bridge MCP config, tokens, and index readiness."""
    from company_brain.doctor.runner import main_exit

    main_exit(
        ["bridge"],
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


@main.group()
def bridge() -> None:
    """Member bridge MCP — tokens, index, manager, HTTP server."""


@bridge.command("serve")
@click.option("--host", default=None, help="Bind host (default from config/bridge.yaml).")
@click.option("--port", type=int, default=None, help="Bind port (default from config/bridge.yaml).")
def bridge_serve(host: str | None, port: int | None) -> None:
    """Run the HTTP MCP server (co-located with wiki host)."""
    from company_brain.bridge.mcp_http import serve

    serve(host=host, port=port)


@bridge.command("issue-token")
@click.argument("member")
def bridge_issue_token(member: str) -> None:
    """Issue a per-member bearer token (plaintext shown once)."""
    from company_brain.bridge.tokens import BridgeTokenStore

    token = BridgeTokenStore().issue(member)
    click.secho(f"Token for {member} (store in COMPANY_BRAIN_MEMBER_TOKEN):", bold=True)
    click.echo(token)
    click.secho("Plaintext is not stored — copy it now.", fg="yellow")


@bridge.command("revoke-token")
@click.argument("member")
def bridge_revoke_token(member: str) -> None:
    """Revoke a member's bridge token."""
    from company_brain.bridge.tokens import BridgeTokenStore

    if BridgeTokenStore().revoke(member):
        click.secho(f"Revoked token for {member}.", fg="green")
    else:
        click.secho(f"No active token for {member}.", fg="yellow")


@bridge.command("rebuild-index")
def bridge_rebuild_index() -> None:
    """Rebuild the bridge search/skills index from wiki pages."""
    from company_brain.bridge.index import rebuild_index

    index = rebuild_index()
    click.echo(
        f"Index rebuilt: {len(index.entries)} entries, {len(index.skills)} dept skill lists."
    )


@bridge.command("manager")
@click.option("--once", is_flag=True, help="Single poll (materialize + optional rollup).")
def bridge_manager(once: bool) -> None:
    """Run bridge_manager (ledger poll + daily rollup scheduler)."""
    from company_brain.agents.bridge.bridge_manager import BridgeManagerAgent

    config = load_config()
    BridgeManagerAgent(config).run(once=once)


@bridge.command("rollup")
def bridge_rollup() -> None:
    """Run blocker rollup once (engineering priorities snapshot)."""
    from company_brain.agents.bridge.blocker_rollup import BlockerRollupAgent

    config = load_config()
    result = BlockerRollupAgent(config).execute()
    click.echo(result)


@main.group()
def slack() -> None:
    """Slack platform — events listener and channel registry admin."""


@slack.group("channel")
def slack_channel() -> None:
    """Admin channel registry commands."""


@slack_channel.command("list")
def slack_channel_list() -> None:
    """List channels in ``config/slack_channels.json``."""
    from company_brain.agents.operations.slack import channels_config

    rows = channels_config.list_channels_summary()
    if not rows:
        click.echo("No channels in registry.")
        return
    for row in rows:
        click.echo(
            f"{row.get('id')}\t{row.get('name', '')}\t"
            f"mode={row.get('ingest_mode', 'hot')}\t"
            f"connect={row.get('is_connect', False)}"
        )


@slack_channel.command("tag")
@click.argument("channel_id")
@click.argument("mode", type=click.Choice(["out-of-scope", "hot", "cold"]))
def slack_channel_tag(channel_id: str, mode: str) -> None:
    """Set channel ingest mode (admin)."""
    from company_brain.agents.operations.slack import channels_config

    normalized = mode.replace("-", "_")
    entry = channels_config.set_ingest_mode(channel_id, normalized)
    click.secho(f"Tagged {channel_id} as {entry.get('ingest_mode')}", fg="green")


@slack_channel.command("enable-connect")
@click.argument("channel_id")
@click.option("--name", default=None, help="Channel display name.")
def slack_channel_enable_connect(channel_id: str, name: str | None) -> None:
    """Enable Slack Connect channel for customer ingest (admin)."""
    from company_brain.agents.operations.slack import channels_config, slack_client

    channels_config.enable_connect_channel(channel_id, name=name)
    if slack_client.join_channel(channel_id):
        channels_config.upsert_channel(channel_id, is_member=True)
    click.secho(f"Enabled Connect ingest for {channel_id}", fg="green")


@slack.command("events")
@click.option("--http", is_flag=True, help="Use HTTP mode instead of Socket Mode.")
@click.option("--host", default="0.0.0.0", help="HTTP bind host.")
@click.option("--port", type=int, default=3000, help="HTTP bind port.")
def slack_events(http: bool, host: str, port: int) -> None:
    """Run the wiki Slack Events API listener (hot lane)."""
    from company_brain.agents.operations.slack.events_server import serve_events

    serve_events(http=http, host=host, port=port)


@slack.command("sync-channels")
def slack_sync_channels() -> None:
    """Sync Slack API channel list into the registry and join internal channels."""
    from company_brain.agents.operations.slack.channel_registry import ChannelRegistryAgent

    config = load_config()
    result = ChannelRegistryAgent(config).run()
    click.echo(result)


@slack.command("thread-absorb")
@click.option("--force", is_flag=True, help="Ignore UTC batch-hour gate.")
def slack_thread_absorb(force: bool) -> None:
    """Distill eligible Slack threads into ``raw/entries`` for absorb (no LLM)."""
    from company_brain.agents.operations.slack.thread_absorb import ThreadAbsorbAgent

    config = load_config()
    result = ThreadAbsorbAgent(config).execute(force=force)
    click.echo(result)


@slack.group("onboarding")
def slack_onboarding_group() -> None:
    """Slack platform onboarding — estimate and backfill."""


@slack_onboarding_group.command("estimate")
@click.option(
    "--days",
    type=int,
    default=None,
    help="Backfill window in days (default from config).",
)
@click.option("--all", "all_history", is_flag=True, help="Estimate full channel history.")
def slack_onboarding_estimate(days: int | None, all_history: bool) -> None:
    """$0 message count estimate for Slack onboarding."""
    from company_brain.agents.operations.slack.slack_onboarding import estimate_backfill

    result = estimate_backfill(days=days, all_history=all_history)
    click.echo(result)


@slack_onboarding_group.command("run")
@click.option("--days", type=int, default=None, help="Operational backfill window.")
@click.option("--all", "all_history", is_flag=True, help="Backfill full history.")
@click.option("--absorb", is_flag=True, help="Run absorb on raw entries after backfill.")
@click.option("--no-manager", is_flag=True, help="Skip starting slack_manager.")
def slack_onboarding_run(
    days: int | None,
    all_history: bool,
    absorb: bool,
    no_manager: bool,
) -> None:
    """Run Slack onboarding backfill and hand off to slack_manager."""
    from company_brain.agents.operations.slack.slack_onboarding import SlackOnboardingAgent

    config = load_config()
    result = SlackOnboardingAgent(config).run(
        start_manager=not no_manager,
        backfill_days=days,
        all_history=all_history,
        absorb=absorb,
    )
    click.echo(result)


@main.group()
def weave() -> None:
    """Weave system-change dispatch."""


@main.group()
def admin() -> None:
    """Admin department — LLM ops, wiki-commit backup, Weave helpers."""


@admin.command("manager")
@click.option("--loop", is_flag=True, help="Run the persistent monthly loop (daemon).")
@click.option("--month", default=None, help="Target month YYYY-MM (default: previous).")
@click.option("--no-sync", is_flag=True, help="Skip Notion sync for wiki writes.")
def admin_manager_cmd(loop: bool, month: str | None, no_sync: bool) -> None:
    """Run admin_manager (monthly LLM expense + maintain). Default: one pass."""
    from company_brain.agents.admin.admin_manager import AdminManager

    config = load_config()
    result = AdminManager(config).execute(once=not loop, month=month, sync=not no_sync)
    if not loop:
        click.echo(result)


@admin.command("expense-report")
@click.option("--month", default=None, help="Target month YYYY-MM (default: previous).")
@click.option("--no-sync", is_flag=True, help="Skip Notion sync.")
def admin_expense_report_cmd(month: str | None, no_sync: bool) -> None:
    """Run llm_expense_report for one month."""
    from company_brain.agents.admin.llm_expense_report import LlmExpenseReportAgent

    config = load_config()
    result = LlmExpenseReportAgent(config).execute(month=month, sync=not no_sync)
    click.echo(result)


@admin.command("maintain")
@click.option("--month", default=None, help="Target month YYYY-MM (default: previous).")
@click.option("--no-sync", is_flag=True, help="Skip Notion sync.")
def admin_maintain_cmd(month: str | None, no_sync: bool) -> None:
    """Run admin_maintain for one month."""
    from company_brain.agents.admin.admin_maintain import AdminMaintainAgent

    config = load_config()
    result = AdminMaintainAgent(config).execute(month=month, sync=not no_sync)
    click.echo(result)


@admin.command("wiki-commit")
@click.option("--loop", is_flag=True, help="Run the persistent daily backup loop.")
@click.option("--force", is_flag=True, help="Bypass hour/once-per-day gates.")
def admin_wiki_commit_cmd(loop: bool, force: bool) -> None:
    """Export MD volume to the admin-only company-wiki git repo."""
    from company_brain.agents.admin.wiki_commit import WikiCommitAgent

    config = load_config()
    result = WikiCommitAgent(config).execute(once=not loop, force=force)
    if not loop:
        click.echo(result)


@admin.command("console")
@click.option("--host", default=None, help="Bind host (default from admin_console.yaml).")
@click.option("--port", type=int, default=None, help="Bind port (default 8780).")
def admin_console_cmd(host: str | None, port: int | None) -> None:
    """Run the admin web console (login required; private mesh)."""
    from company_brain.admin_console.server import serve

    serve(host=host, port=port)


@weave.command("events")
@click.option("--http", is_flag=True, help="Use HTTP mode instead of Socket Mode.")
@click.option("--host", default="0.0.0.0", help="HTTP bind host.")
@click.option("--port", type=int, default=3001, help="HTTP bind port.")
def weave_events(http: bool, host: str, port: int) -> None:
    """Run the Weave Slack Events API listener."""
    from company_brain.agents.operations.slack.weave_events_server import serve_weave_events

    serve_weave_events(http=http, host=host, port=port)


@weave.command("poll-approvals")
@click.option(
    "--builder",
    type=click.Choice(["codex", "in_house", "off"]),
    default=None,
    help="Override weave.builder for dispatched implement+prove runs.",
)
def weave_poll_approvals(builder: str | None) -> None:
    """Dispatch weave for Notion-approved change requests."""
    import os

    from company_brain.agents.admin.weave_triage import WeaveTriageAgent

    if builder:
        os.environ["WEAVE_BUILDER"] = builder
    config = load_config()
    result = WeaveTriageAgent(config).run(poll_approvals=True)
    click.echo(result)


@main.group()
def discord() -> None:
    """Discord community platform — Gateway listener and channel registry."""


@discord.command("gateway")
def discord_gateway() -> None:
    """Run the Discord Gateway WebSocket listener (hot lane)."""
    from company_brain.agents.growth.discord.discord_gateway import serve_gateway

    serve_gateway()


@discord.command("sync-channels")
def discord_sync_channels() -> None:
    """Sync Discord guild channels into ``config/discord_channels.json``."""
    from company_brain.agents.growth.discord import discord_config as cfg
    from company_brain.agents.growth.discord.events_router import sync_guild_channels

    guild_id = cfg.guild_id()
    if not guild_id:
        raise click.ClickException("Set discord.guild_id in config/growth.yaml")
    result = sync_guild_channels(guild_id)
    click.echo(result)


@discord.group("channel")
def discord_channel() -> None:
    """Admin Discord channel registry commands."""


@discord_channel.command("list")
def discord_channel_list() -> None:
    """List channels in ``config/discord_channels.json``."""
    from company_brain.agents.growth.discord import channels_config

    rows = channels_config.list_channels_summary()
    if not rows:
        click.echo("No channels in registry. Run: company-brain discord sync-channels")
        return
    for row in rows:
        click.echo(
            f"{row.get('id')}\t{row.get('name', '')}\t"
            f"mode={row.get('ingest_mode', 'hot')}\t"
            f"type={row.get('type', '')}"
        )


@discord.command("manager")
def discord_manager_cmd() -> None:
    """Run the persistent Discord manager loop."""
    from company_brain.agents.growth.discord_manager import DiscordManager

    config = load_config()
    DiscordManager(config).run()


@discord.group("onboarding")
def discord_onboarding_group() -> None:
    """Discord platform onboarding — estimate and backfill."""


@discord_onboarding_group.command("estimate")
@click.option(
    "--days",
    type=int,
    default=None,
    help="Backfill window in days (default from config).",
)
@click.option("--all", "all_history", is_flag=True, help="Estimate full channel history.")
def discord_onboarding_estimate(days: int | None, all_history: bool) -> None:
    """$0 message count estimate for Discord onboarding."""
    from company_brain.agents.growth.discord.discord_onboarding import estimate_backfill

    result = estimate_backfill(days=days, all_history=all_history)
    click.echo(result)


@discord_onboarding_group.command("run")
@click.option("--days", type=int, default=None, help="Backfill window in days.")
@click.option("--all", "all_history", is_flag=True, help="Backfill full channel history.")
@click.option("--no-manager", is_flag=True, help="Skip starting discord_manager.")
@click.option("--absorb", is_flag=True, help="Queue technical threads and run absorb.")
def discord_onboarding_run(
    days: int | None,
    all_history: bool,
    no_manager: bool,
    absorb: bool,
) -> None:
    """Run Discord onboarding backfill and start the manager."""
    from company_brain.agents.growth.discord.discord_onboarding import DiscordOnboardingAgent

    config = load_config()
    result = DiscordOnboardingAgent(config).run(
        start_manager=not no_manager,
        backfill_days=days,
        all_history=all_history,
        absorb=absorb,
    )
    click.echo(result)


@main.group("google-ads")
def google_ads() -> None:
    """Google Ads — read-only weekly campaign / pacing / CPA snapshots."""


@google_ads.command("manager")
@click.option("--once", is_flag=True, help="Run one snapshot pass and exit.")
@click.option("--force", is_flag=True, help="Ignore the weekly cost gate (with --once).")
def google_ads_manager_cmd(once: bool, force: bool) -> None:
    """Run the persistent Google Ads manager loop (or one pass with --once)."""
    from company_brain.agents.growth.google_ads_manager import GoogleAdsManager

    config = load_config()
    manager = GoogleAdsManager(config)
    if once:
        click.echo(manager.run(once=True, force=force))
        return
    manager.run()


@google_ads.group("onboarding")
def google_ads_onboarding_group() -> None:
    """Google Ads platform onboarding — snapshot and start manager."""


@google_ads_onboarding_group.command("run")
@click.option("--no-manager", is_flag=True, help="Skip starting google_ads_manager.")
def google_ads_onboarding_run(no_manager: bool) -> None:
    """Run Google Ads snapshot specialists and start the weekly manager."""
    from company_brain.agents.growth.google_ads.google_ads_onboarding import (
        GoogleAdsOnboardingAgent,
    )

    config = load_config()
    result = GoogleAdsOnboardingAgent(config).run(start_manager=not no_manager)
    click.echo(result)


@main.group("growth")
def growth() -> None:
    """Growth workstreams — activity, content, competitor, leads."""


@growth.command("onboarding")
@click.option("--no-managers", is_flag=True, help="Skip starting workstream managers.")
def growth_onboarding_cmd(no_managers: bool) -> None:
    """Seed growth workstream pages and start workstream managers."""
    from company_brain.agents.growth.growth_onboarding import GrowthOnboardingAgent

    config = load_config()
    result = GrowthOnboardingAgent(config).run(start_managers=not no_managers)
    click.echo(result)


@growth.group("event")
def growth_event() -> None:
    """Company activity — register / plan / partner / wrap."""


@growth_event.command("register")
@click.argument("name")
@click.option("--date", default="", help="Event date YYYY-MM-DD.")
@click.option("--format", "event_format", default="", help="Event format.")
@click.option("--notes", default="", help="Extra context.")
@click.option("--quiet", is_flag=True, help="Skip Slack notify.")
def growth_event_register(name: str, date: str, event_format: str, notes: str, quiet: bool) -> None:
    """Register a company event (human-gated)."""
    from company_brain.agents.growth.activity.event_register import EventRegisterAgent

    config = load_config()
    result = EventRegisterAgent(config).run(
        name=name,
        date=date,
        format=event_format,
        notes=notes,
        source="cli",
        notify=not quiet,
    )
    click.echo(result)


@growth_event.command("plan")
@click.argument("slug")
@click.option("--notes", default="", help="Extra context to append.")
def growth_event_plan(slug: str, notes: str) -> None:
    """Run assisted planning on a registered event."""
    from company_brain.agents.growth.activity.event_plan import EventPlanAgent

    config = load_config()
    click.echo(EventPlanAgent(config).run(slug=slug, extra_notes=notes))


@growth_event.command("partner")
@click.argument("slug")
@click.argument("partner_name")
@click.option("--bio", default="")
@click.option("--email", default="")
@click.option("--logo-notes", default="")
def growth_event_partner(
    slug: str, partner_name: str, bio: str, email: str, logo_notes: str
) -> None:
    """Draft a partnership one-pager for an event."""
    from company_brain.agents.growth.activity.partnership_brief import PartnershipBriefAgent

    config = load_config()
    click.echo(
        PartnershipBriefAgent(config).run(
            slug=slug,
            partner_name=partner_name,
            partner_bio=bio,
            partner_email=email,
            logo_notes=logo_notes,
        )
    )


@growth_event.command("wrap")
@click.argument("slug")
@click.option(
    "--attendees-csv",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Attendee CSV to queue for lead research.",
)
@click.option("--quiet", is_flag=True, help="Skip Slack notify.")
def growth_event_wrap(slug: str, attendees_csv: Path | None, quiet: bool) -> None:
    """Wrap an event and queue content drafts + optional lead research."""
    from company_brain.agents.growth.activity.event_wrap import EventWrapAgent

    csv_text = attendees_csv.read_text(encoding="utf-8") if attendees_csv else ""
    config = load_config()
    click.echo(EventWrapAgent(config).run(slug=slug, attendees_csv=csv_text, notify=not quiet))


@growth.command("activity-manager")
@click.option("--once", is_flag=True, help="Run one pass and exit.")
def growth_activity_manager(once: bool) -> None:
    """Run the activity workstream manager."""
    from company_brain.agents.growth.activity_manager import ActivityManager

    config = load_config()
    mgr = ActivityManager(config)
    click.echo(mgr.run(once=True) if once else mgr.run())


@growth.command("content-manager")
@click.option("--once", is_flag=True, help="Run one pass and exit.")
def growth_content_manager(once: bool) -> None:
    """Run the content workstream manager."""
    from company_brain.agents.growth.content_manager import ContentManager

    config = load_config()
    mgr = ContentManager(config)
    click.echo(mgr.run(once=True) if once else mgr.run())


@growth.command("competitor-manager")
@click.option("--once", is_flag=True, help="Run one pass and exit.")
@click.option("--force", is_flag=True, help="Ignore monthly cost gate.")
def growth_competitor_manager(once: bool, force: bool) -> None:
    """Run the competitor workstream manager."""
    from company_brain.agents.growth.competitor_manager import CompetitorManager

    config = load_config()
    mgr = CompetitorManager(config)
    if once:
        click.echo(mgr.run(once=True, force=force))
        return
    mgr.run()


@growth.command("lead-manager")
@click.option("--once", is_flag=True, help="Run one pass and exit.")
def growth_lead_manager(once: bool) -> None:
    """Run the lead research workstream manager."""
    from company_brain.agents.growth.lead_manager import LeadManager

    config = load_config()
    mgr = LeadManager(config)
    click.echo(mgr.run(once=True) if once else mgr.run())


@growth.group("leads")
def growth_leads() -> None:
    """Lead research queue helpers."""


@growth_leads.command("enqueue")
@click.option(
    "--source",
    type=click.Choice(["attendee_csv", "github_stargazers", "uploaded_list"]),
    required=True,
)
@click.option("--label", default="", help="Job label.")
@click.option("--repo", default="", help="org/repo for github_stargazers.")
@click.option(
    "--csv",
    "csv_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
)
def growth_leads_enqueue(source: str, label: str, repo: str, csv_path: Path | None) -> None:
    """Enqueue a lead research job."""
    from company_brain.agents.growth.leads.queue import enqueue_lead_job

    payload: dict = {}
    if source in {"attendee_csv", "uploaded_list"}:
        if not csv_path:
            raise click.ClickException("--csv required for this source")
        payload["csv_text"] = csv_path.read_text(encoding="utf-8")
    if source == "github_stargazers":
        if not repo:
            raise click.ClickException("--repo required for github_stargazers")
        payload["repo"] = repo
    job = enqueue_lead_job(
        source=source,
        label=label or source,
        payload=payload,
    )
    click.echo(job)


@growth.command("draft")
@click.argument("channel", type=click.Choice(["blog", "x", "linkedin"]))
@click.argument("instructions")
@click.option("--title", default="")
@click.option("--author", default="")
def growth_draft(channel: str, instructions: str, title: str, author: str) -> None:
    """Create a content draft (never posts)."""
    from company_brain.agents.growth.content.draft_writer import DraftWriterAgent

    config = load_config()
    click.echo(
        DraftWriterAgent(config).run(
            channel=channel,
            instructions=instructions,
            title=title,
            suggested_author=author,
        )
    )


@growth.command("published-pull")
@click.option(
    "--item",
    "items",
    multiple=True,
    help="channel|title|url|text (repeatable).",
)
@click.option("--force", is_flag=True)
def growth_published_pull(items: tuple[str, ...], force: bool) -> None:
    """Ingest published company content; retire drafts; refresh voice."""
    from company_brain.agents.growth.content.published_pull import PublishedPullAgent

    parsed = []
    for raw in items:
        parts = raw.split("|", 3)
        while len(parts) < 4:
            parts.append("")
        parsed.append(
            {
                "channel": parts[0],
                "title": parts[1],
                "url": parts[2],
                "text": parts[3],
            }
        )
    config = load_config()
    click.echo(PublishedPullAgent(config).run(items=parsed, force=force))


@main.group()
def hr() -> None:
    """HR roster and offboarding helpers."""


@hr.command("promote")
@click.argument("roster_key")
@click.option("--member-key", default=None, help="members.yaml key (default: roster key).")
@click.option("--role", default="member", type=click.Choice(["admin", "member"]))
def hr_promote(roster_key: str, member_key: str | None, role: str) -> None:
    """Promote a roster person into members.yaml (W2)."""
    from company_brain.agents.hr.hiring_log import append_hiring_log
    from company_brain.roster_config import promote_roster_to_member

    key = promote_roster_to_member(roster_key, member_key=member_key, role=role)
    append_hiring_log(
        f"Promoted {roster_key} → {key}",
        f"Roster key `{roster_key}` promoted to members.yaml as `{key}` (`role={role}`).",
        trigger="hr_promote",
        why=roster_key,
    )
    click.secho(f"Promoted to members.yaml: {key}", fg="green")


@hr.command("offboard")
@click.argument("member_key")
@click.option("--reason", default="manual", help="Offboarding reason label.")
def hr_offboard(member_key: str, reason: str) -> None:
    """Create an offboarding proposal for a member."""
    from company_brain.agents.hr.employee_offboarding import EmployeeOffboardingAgent

    config = load_config()
    result = EmployeeOffboardingAgent(config).run(member_key=member_key, reason=reason)
    click.echo(result)


@main.group()
def notion() -> None:
    """Notion platform — manager, page sync pull, task scanner."""


@notion.command("manager")
@click.option("--once", is_flag=True, help="Run a single manager pass then exit.")
def notion_manager_cmd(once: bool) -> None:
    """Run the persistent Notion manager (sync_pull + task_scanner)."""
    from company_brain.agents.operations.notion_manager import NotionManager

    config = load_config()
    result = NotionManager(config).execute(once=once)
    if once:
        click.echo(result)


@notion.command("sync-pull")
def notion_sync_pull_cmd() -> None:
    """Run one sync_pull pass (Notion → MD for bound pages)."""
    from company_brain.agents.operations.notion.sync_pull import SyncPullAgent

    config = load_config()
    result = SyncPullAgent(config).execute()
    click.echo(result)


@notion.group("onboarding")
def notion_onboarding_group() -> None:
    """Notion platform onboarding — ingest and alongside structure."""


@notion_onboarding_group.command("run")
@click.option(
    "--confirm-mirror",
    is_flag=True,
    help="Build alongside 4r7a Notion tree + enable mirror (required if workspace has pages).",
)
@click.option("--no-manager", is_flag=True, help="Skip starting notion_manager.")
@click.option("--no-ingest", is_flag=True, help="Skip ingesting existing Notion pages into MD.")
def notion_onboarding_run(confirm_mirror: bool, no_manager: bool, no_ingest: bool) -> None:
    """Run Notion onboarding (warns before large reorg unless --confirm-mirror)."""
    from company_brain.agents.operations.notion.notion_onboarding import NotionOnboardingAgent

    if not confirm_mirror:
        click.secho(
            "Note: without --confirm-mirror, existing Notion pages are ingested to MD only; "
            "structured mirror/sync is not established. Re-run with --confirm-mirror after review.",
            fg="yellow",
        )
    config = load_config()
    result = NotionOnboardingAgent(config).execute(
        confirm_mirror=confirm_mirror,
        start_manager=not no_manager,
        ingest_existing=not no_ingest,
    )
    click.echo(result)
