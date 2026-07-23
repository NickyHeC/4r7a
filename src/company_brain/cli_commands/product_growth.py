"""Product, growth, analytics, and community platform CLI commands."""

from __future__ import annotations

from pathlib import Path

import click

from company_brain.config import load_config


@click.group()
def discord() -> None:
    """Discord community platform — Gateway listener and channel registry."""


@discord.command("gateway")
def discord_gateway() -> None:
    """Run the Discord Gateway WebSocket listener (hot lane)."""
    from company_brain.agents.growth.discord.gateway import serve_gateway

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
    DiscordManager(config).execute(once=False)


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
    result = DiscordOnboardingAgent(config).execute(
        start_manager=not no_manager,
        backfill_days=days,
        all_history=all_history,
        absorb=absorb,
    )
    click.echo(result)


@click.group("posthog")
def posthog() -> None:
    """PostHog — read-only weekly product analytics snapshots."""


@posthog.command("manager")
@click.option("--once", is_flag=True, help="Run one snapshot pass and exit.")
@click.option("--force", is_flag=True, help="Ignore the weekly cost gate (with --once).")
def posthog_manager_cmd(once: bool, force: bool) -> None:
    """Run the persistent PostHog manager loop (or one pass with --once)."""
    from company_brain.agents.product.posthog_manager import PosthogManager

    config = load_config()
    manager = PosthogManager(config)
    if once:
        click.echo(manager.execute(once=True, force=force))
        return
    manager.execute(once=False)


@posthog.group("onboarding")
def posthog_onboarding_group() -> None:
    """PostHog platform onboarding — snapshot and start manager."""


@posthog_onboarding_group.command("run")
@click.option("--no-manager", is_flag=True, help="Skip starting posthog_manager.")
def posthog_onboarding_run(no_manager: bool) -> None:
    """Run PostHog specialists (30d lookback when data exists) and start the manager."""
    from company_brain.agents.product.posthog.posthog_onboarding import PosthogOnboardingAgent

    config = load_config()
    result = PosthogOnboardingAgent(config).execute(start_manager=not no_manager)
    click.echo(result)


@click.group("product")
def product() -> None:
    """Product workstreams — update, use cases, docs, progress, attribution."""


@product.command("onboarding")
@click.option("--no-managers", is_flag=True, help="Skip starting workstream managers.")
def product_onboarding_cmd(no_managers: bool) -> None:
    """Seed product workstream pages and start workstream managers."""
    from company_brain.agents.product.product_onboarding import ProductOnboardingAgent

    config = load_config()
    click.echo(ProductOnboardingAgent(config).execute(start_managers=not no_managers))


@product.command("update-manager")
@click.option("--once", is_flag=True)
@click.option("--force", is_flag=True)
def product_update_manager(once: bool, force: bool) -> None:
    from company_brain.agents.product.update_manager import UpdateManager

    config = load_config()
    mgr = UpdateManager(config)
    click.echo(mgr.execute(once=True, force=force) if once else mgr.execute(once=False))


@product.command("use-case-manager")
@click.option("--once", is_flag=True)
@click.option("--force", is_flag=True)
def product_use_case_manager(once: bool, force: bool) -> None:
    from company_brain.agents.product.use_case_manager import UseCaseManager

    config = load_config()
    mgr = UseCaseManager(config)
    click.echo(mgr.execute(once=True, force=force) if once else mgr.execute(once=False))


@product.command("docs-manager")
@click.option("--once", is_flag=True)
@click.option("--force", is_flag=True)
def product_docs_manager(once: bool, force: bool) -> None:
    from company_brain.agents.product.docs_manager import DocsManager

    config = load_config()
    mgr = DocsManager(config)
    click.echo(mgr.execute(once=True, force=force) if once else mgr.execute(once=False))


@product.command("progress-manager")
@click.option("--once", is_flag=True)
@click.option("--force", is_flag=True)
def product_progress_manager(once: bool, force: bool) -> None:
    from company_brain.agents.product.progress_manager import ProgressManager

    config = load_config()
    mgr = ProgressManager(config)
    click.echo(mgr.execute(once=True, force=force) if once else mgr.execute(once=False))


@product.command("attribution-manager")
@click.option("--once", is_flag=True)
@click.option("--force", is_flag=True)
def product_attribution_manager(once: bool, force: bool) -> None:
    from company_brain.agents.product.attribution_manager import AttributionManager

    config = load_config()
    mgr = AttributionManager(config)
    click.echo(mgr.execute(once=True, force=force) if once else mgr.execute(once=False))


@product.command("newsletter")
@click.option("--month", default=None, help="YYYY-MM (default: current month).")
@click.option("--force", is_flag=True)
def product_newsletter(month: str | None, force: bool) -> None:
    """Draft the customer product newsletter (wiki only; never sends)."""
    from company_brain.agents.product.update.product_update import ProductUpdateAgent

    config = load_config()
    click.echo(ProductUpdateAgent(config).execute(month=month, force=force))


@product.command("docs-audit")
@click.option("--force", is_flag=True)
def product_docs_audit(force: bool) -> None:
    from company_brain.agents.product.docs.audit import DocsAuditAgent

    config = load_config()
    click.echo(DocsAuditAgent(config).execute(force=force))


@product.command("progress")
@click.option("--force", is_flag=True)
def product_progress(force: bool) -> None:
    from company_brain.agents.product.progress.compile import ProgressCompileAgent

    config = load_config()
    click.echo(ProgressCompileAgent(config).execute(force=force))


@product.command("signup-match")
@click.option("--force", is_flag=True)
def product_signup_match(force: bool) -> None:
    from company_brain.agents.product.attribution.signup_match import SignupMatchAgent

    config = load_config()
    click.echo(SignupMatchAgent(config).execute(force=force))


@product.command("use-cases")
@click.option("--force", is_flag=True)
def product_use_cases(force: bool) -> None:
    from company_brain.agents.product.use_case.track import UseCaseTrackAgent

    config = load_config()
    click.echo(UseCaseTrackAgent(config).execute(force=force))


@click.group("google-ads")
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
        click.echo(manager.execute(once=True, force=force))
        return
    manager.execute(once=False)


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
    result = GoogleAdsOnboardingAgent(config).execute(start_manager=not no_manager)
    click.echo(result)


@click.group("growth")
def growth() -> None:
    """Growth workstreams — activity, content, competitor, leads."""


@growth.command("onboarding")
@click.option("--no-managers", is_flag=True, help="Skip starting workstream managers.")
def growth_onboarding_cmd(no_managers: bool) -> None:
    """Seed growth workstream pages and start workstream managers."""
    from company_brain.agents.growth.growth_onboarding import GrowthOnboardingAgent

    config = load_config()
    result = GrowthOnboardingAgent(config).execute(start_managers=not no_managers)
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
    result = EventRegisterAgent(config).execute(
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
    click.echo(EventPlanAgent(config).execute(slug=slug, extra_notes=notes))


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
        PartnershipBriefAgent(config).execute(
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
    click.echo(EventWrapAgent(config).execute(slug=slug, attendees_csv=csv_text, notify=not quiet))


@growth.command("activity-manager")
@click.option("--once", is_flag=True, help="Run one pass and exit.")
def growth_activity_manager(once: bool) -> None:
    """Run the activity workstream manager."""
    from company_brain.agents.growth.activity_manager import ActivityManager

    config = load_config()
    mgr = ActivityManager(config)
    click.echo(mgr.execute(once=True) if once else mgr.execute(once=False))


@growth.command("content-manager")
@click.option("--once", is_flag=True, help="Run one pass and exit.")
def growth_content_manager(once: bool) -> None:
    """Run the content workstream manager."""
    from company_brain.agents.growth.content_manager import ContentManager

    config = load_config()
    mgr = ContentManager(config)
    click.echo(mgr.execute(once=True) if once else mgr.execute(once=False))


@growth.command("competitor-manager")
@click.option("--once", is_flag=True, help="Run one pass and exit.")
@click.option("--force", is_flag=True, help="Ignore monthly cost gate.")
def growth_competitor_manager(once: bool, force: bool) -> None:
    """Run the competitor workstream manager."""
    from company_brain.agents.growth.competitor_manager import CompetitorManager

    config = load_config()
    mgr = CompetitorManager(config)
    if once:
        click.echo(mgr.execute(once=True, force=force))
        return
    mgr.execute(once=False)


@growth.command("lead-manager")
@click.option("--once", is_flag=True, help="Run one pass and exit.")
def growth_lead_manager(once: bool) -> None:
    """Run the lead research workstream manager."""
    from company_brain.agents.growth.lead_manager import LeadManager

    config = load_config()
    mgr = LeadManager(config)
    click.echo(mgr.execute(once=True) if once else mgr.execute(once=False))


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
        DraftWriterAgent(config).execute(
            channel=channel,
            instructions=instructions,
            title=title,
            suggested_author=author,
            force=True,
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
    click.echo(PublishedPullAgent(config).execute(items=parsed, force=force))


def register(main: click.Group) -> None:
    main.add_command(discord)
    main.add_command(posthog)
    main.add_command(product)
    main.add_command(google_ads)
    main.add_command(growth)
