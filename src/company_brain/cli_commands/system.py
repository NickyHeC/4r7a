"""CRM and model configuration CLI commands."""

from __future__ import annotations

import click


@click.group()
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


@click.group()
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


def register(main: click.Group) -> None:
    main.add_command(crm)
    main.add_command(models)
