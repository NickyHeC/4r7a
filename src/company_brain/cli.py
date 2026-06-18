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
    resolve_llm_provider,
    resolve_mode,
    resolve_runtime,
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
@click.option("--since", type=click.DateTime(), default=None, help="Only absorb entries after this date.")
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


@main.command()
def doctor() -> None:
    """Diagnose setup: deployment mode, wiki location, and platform connections.

    Used during agent-assisted onboarding to verify each platform after it is
    connected. Reads only — never mutates anything.
    """
    import os
    import shutil

    click.secho("company-brain doctor", bold=True)
    click.echo(f"  Mode:        {resolve_mode()}")
    click.echo(f"  Runtime:     {resolve_runtime()}")
    click.echo(f"  Wiki dir:    {resolve_wiki_dir()}")
    click.echo(f"  Sandbox:     {os.getenv('COMPANY_BRAIN_SANDBOX', 'off')}")

    provider_line = resolve_llm_provider()
    provider_hint = ""
    try:
        from company_brain.llm.provider import resolve_provider

        p = resolve_provider()
        model = p.model or "(SDK default)"
        target = p.base_url or "hosted API"
        provider_line = f"{p.key} (sdk={p.sdk}, model={model}, {target})"
    except Exception as exc:  # misconfigured provider — surface, don't crash doctor
        provider_hint = f"  -> {exc}"
    click.echo(f"  LLM:         {provider_line}")
    if provider_hint:
        click.secho(provider_hint, fg="yellow")
    click.echo()

    def check(label: str, ok: bool, hint: str) -> None:
        mark = click.style("OK ", fg="green") if ok else click.style("-- ", fg="yellow")
        click.echo(f"  [{mark}] {label}" + ("" if ok else f"  ({hint})"))

    notion_ok = False
    if shutil.which("ntn"):
        try:
            from company_brain.notion.client import NotionClient
            notion_ok = NotionClient().check_auth()
        except Exception:
            notion_ok = False
    check("Notion CLI (ntn) authenticated", notion_ok, "install ntn + run 'ntn login', then 'company-brain init'")

    check("GitHub CLI (gh) installed", shutil.which("gh") is not None, "install gh (read-only)")
    check("Mercury token (read-only)", bool(os.getenv("MERCURY_TOKEN")), "set MERCURY_TOKEN")
    check("Ramp token (read-only)", bool(os.getenv("RAMP_TOKEN")), "set RAMP_TOKEN + Ramp MCP")
    check("Slack bot token", bool(os.getenv("SLACK_BOT_TOKEN")), "set SLACK_BOT_TOKEN")

    provider = resolve_llm_provider()
    if provider == "glm":
        check(
            "GLM-5 endpoint (open-source, no external tokens)", bool(os.getenv("GLM_BASE_URL")),
            "set GLM_BASE_URL to your OpenAI-compatible GLM-5 server (cloud self-host or remote host)",
        )
    elif provider == "openai":
        check("OpenAI API key", bool(os.getenv("OPENAI_API_KEY")), "set OPENAI_API_KEY")
    else:
        check("Anthropic API key", bool(os.getenv("ANTHROPIC_API_KEY")), "set ANTHROPIC_API_KEY")

    try:
        from company_brain.agents.operations.gmail import gmail_client as gmail
        gmail_ok, gmail_provider = gmail.gmail_is_configured(), gmail.gmail_provider()
    except Exception:
        gmail_ok, gmail_provider = False, "official"
    check(
        f"Gmail connection ({gmail_provider}, read+draft)", gmail_ok,
        "set Gmail OAuth (official) or COMPOSIO_API_KEY (composio) — see project_install.md",
    )

    config = load_config()
    check("Wiki initialized in Notion", config.notion.is_initialized, "run 'company-brain init'")
    click.echo()
    click.echo("Connect platforms with the help of an AI coding agent — see project_install.md.")
