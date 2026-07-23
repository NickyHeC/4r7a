"""Bridge, Slack, and Weave collaboration CLI commands."""

from __future__ import annotations

import click

from company_brain.config import load_config


@click.group()
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
    BridgeManagerAgent(config).execute(once=once)


@bridge.command("rollup")
def bridge_rollup() -> None:
    """Run blocker rollup once (engineering priorities snapshot)."""
    from company_brain.agents.bridge.blocker_rollup import BlockerRollupAgent

    config = load_config()
    result = BlockerRollupAgent(config).execute()
    click.echo(result)


@click.group()
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
    result = ChannelRegistryAgent(config).execute()
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
    result = SlackOnboardingAgent(config).execute(
        start_manager=not no_manager,
        backfill_days=days,
        all_history=all_history,
        absorb=absorb,
    )
    click.echo(result)


@click.group()
def weave() -> None:
    """Weave system-change dispatch."""


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
    result = WeaveTriageAgent(config).execute(poll_approvals=True)
    click.echo(result)


def register(main: click.Group) -> None:
    main.add_command(bridge)
    main.add_command(slack)
    main.add_command(weave)
