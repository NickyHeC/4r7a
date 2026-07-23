"""Administrative maintenance, fleet, console, and knowledge CLI commands."""

from __future__ import annotations

import click

from company_brain.config import load_config


@click.group()
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


@admin.command("upstream-sync")
@click.option("--force", is_flag=True, help="Bypass monthly already-ran gate.")
def admin_upstream_sync_cmd(force: bool) -> None:
    """Open a filtered draft PR from public 4r7a into the private brain repo."""
    from company_brain.agents.admin.upstream_sync import UpstreamSyncAgent

    config = load_config()
    result = UpstreamSyncAgent(config).execute(force=force)
    click.echo(result)


@admin.command("process-scout")
@click.option("--month", default=None, help="Target month YYYY-MM (default: previous).")
@click.option("--no-sync", is_flag=True, help="Skip Notion sync.")
def admin_process_scout_cmd(month: str | None, no_sync: bool) -> None:
    """Write monthly process scout review page (proposals only)."""
    from company_brain.agents.admin.process_scout import ProcessScoutAgent

    config = load_config()
    result = ProcessScoutAgent(config).execute(month=month, sync=not no_sync)
    click.echo(result)


@admin.command("wiki-ops-audit")
@click.option("--month", default=None, help="Target month YYYY-MM (default: previous).")
@click.option("--no-sync", is_flag=True, help="Skip Notion sync.")
def admin_wiki_ops_audit_cmd(month: str | None, no_sync: bool) -> None:
    """Write monthly wiki ops audit review page (never auto-apply)."""
    from company_brain.agents.admin.wiki_ops_audit import WikiOpsAuditAgent

    config = load_config()
    result = WikiOpsAuditAgent(config).execute(month=month, sync=not no_sync)
    click.echo(result)


@admin.command("doc-hygiene")
@click.option("--period", default=None, help="Period label e.g. 2026-Q3 (default: current).")
@click.option("--no-sync", is_flag=True, help="Skip Notion sync.")
def admin_doc_hygiene_cmd(period: str | None, no_sync: bool) -> None:
    """Write quarterly doc hygiene review page (never auto-edit docs)."""
    from company_brain.agents.admin.doc_hygiene import DocHygieneAgent

    config = load_config()
    result = DocHygieneAgent(config).execute(period=period, sync=not no_sync)
    click.echo(result)


@admin.command("self-heal")
@click.option("--agent-name", required=True, help="Agent that failed verify / raised.")
@click.option("--reason", required=True, help="Short reason string.")
@click.option("--detail", default="", help="Optional detail for the queue entry.")
@click.option("--head", default=None, help="Optional git branch for a draft PR.")
@click.option("--no-sync", is_flag=True, help="Skip Notion sync.")
def admin_self_heal_cmd(
    agent_name: str,
    reason: str,
    detail: str,
    head: str | None,
    no_sync: bool,
) -> None:
    """Queue a self-heal proposal (never auto-merges)."""
    from company_brain.agents.admin.self_heal import SelfHealAgent

    config = load_config()
    result = SelfHealAgent(config).execute(
        agent_name=agent_name,
        reason=reason,
        detail=detail,
        head=head,
        sync=not no_sync,
    )
    click.echo(result)


@admin.group("fleet")
def admin_fleet_group() -> None:
    """Fleet pause / resume / redeploy cue."""


@admin_fleet_group.command("status")
def admin_fleet_status_cmd() -> None:
    """Print fleet pause + redeploy snapshot."""
    import json as json_lib

    from company_brain.runtime.fleet_gate import redeploy_instructions, snapshot

    snap = snapshot()
    click.echo(json_lib.dumps(snap, indent=2))
    cue = redeploy_instructions()
    if cue:
        click.secho("\n" + cue, fg="yellow")


@admin_fleet_group.command("pause")
def admin_fleet_pause_cmd() -> None:
    """Request fleet pause (managers finish busy work, then stop dispatch)."""
    import json as json_lib

    from company_brain.runtime.fleet_gate import request_pause

    click.echo(json_lib.dumps(request_pause(by="cli"), indent=2))


@admin_fleet_group.command("resume")
def admin_fleet_resume_cmd() -> None:
    """Clear fleet pause so managers may dispatch again."""
    import json as json_lib

    from company_brain.runtime.fleet_gate import resume

    click.echo(json_lib.dumps(resume(by="cli"), indent=2))


@admin_fleet_group.command("request-redeploy")
@click.option("--sha", default="", help="Merged commit SHA.")
@click.option("--pr-url", default="", help="Merged PR URL.")
@click.option("--note", default="", help="Optional note.")
def admin_fleet_request_redeploy_cmd(sha: str, pr_url: str, note: str) -> None:
    """Set redeploy cue for the next admin / install skill session."""
    import json as json_lib

    from company_brain.runtime.fleet_gate import request_redeploy

    click.echo(
        json_lib.dumps(
            request_redeploy(sha=sha, pr_url=pr_url, by="cli", note=note),
            indent=2,
        )
    )


@admin_fleet_group.command("clear-redeploy")
def admin_fleet_clear_redeploy_cmd() -> None:
    """Clear the redeploy cue after managers were restarted."""
    from company_brain.runtime.fleet_gate import clear_redeploy

    clear_redeploy()
    click.echo("cleared")


@admin.command("console")
@click.option("--host", default=None, help="Bind host (default from admin_console.yaml).")
@click.option("--port", type=int, default=None, help="Bind port (default 8780).")
def admin_console_cmd(host: str | None, port: int | None) -> None:
    """Run the admin web console (login required; private mesh)."""
    from company_brain.admin_console.server import serve

    serve(host=host, port=port)


@admin.command("investor-newsletter")
@click.option("--month", default=None, help="Target month YYYY-MM (default: current).")
@click.option("--force", is_flag=True, help="Overwrite existing draft.")
@click.option("--no-sync", is_flag=True, help="Skip Notion sync.")
def admin_investor_newsletter_cmd(month: str | None, force: bool, no_sync: bool) -> None:
    """Draft monthly investor newsletter (admin_only; never sends)."""
    from company_brain.agents.admin.investor_newsletter import InvestorNewsletterAgent

    config = load_config()
    result = InvestorNewsletterAgent(config).execute(month=month, force=force, sync=not no_sync)
    click.echo(result)


@admin.group("knowledge")
def admin_knowledge_group() -> None:
    """Safe paste-in of miscellaneous external knowledge."""


@admin_knowledge_group.command("paste")
@click.option("--title", required=True, help="Note title.")
@click.option("--body", default="", help="Markdown body (or use --file / stdin).")
@click.option("--file", "file_path", default="", help="Read body from a .md file.")
@click.option("--dest", default=None, help="Promote dest path (default admin/knowledge/{slug}.md).")
@click.option("--to-raw", is_flag=True, help="On approve, write raw/entries for absorb.")
@click.option(
    "--sync-label",
    default="admin_only",
    help="Frontmatter sync label (admin_only|company|location:…).",
)
@click.option("--approve", is_flag=True, help="Promote immediately if scan passes.")
@click.option(
    "--force-approve",
    is_flag=True,
    help="Promote even if scan blocked (audited; use sparingly).",
)
def admin_knowledge_paste_cmd(
    title: str,
    body: str,
    file_path: str,
    dest: str | None,
    to_raw: bool,
    sync_label: str,
    approve: bool,
    force_approve: bool,
) -> None:
    """Quarantine + scan a pasted note; open admin knowledge-review page."""
    import sys

    from company_brain.agents.admin.knowledge_paste import KnowledgePasteAgent

    if not body and not file_path and not sys.stdin.isatty():
        body = sys.stdin.read()
    config = load_config()
    result = KnowledgePasteAgent(config).execute(
        title=title,
        body=body,
        file_path=file_path,
        dest=dest,
        to_raw=to_raw,
        sync_label=sync_label,
        approve=approve,
        force_approve=force_approve,
    )
    click.echo(result)


@admin_knowledge_group.command("approve")
@click.option("--import-id", required=True, help="Paste import id from review page.")
@click.option("--title", default="Knowledge note", help="Article title.")
@click.option("--dest", default=None, help="Wiki dest path (broader company path allowed).")
@click.option("--to-raw", is_flag=True, help="Write raw/entries instead of wiki page.")
@click.option("--sync-label", default="admin_only", help="Frontmatter sync label.")
@click.option("--force", is_flag=True, help="Force promote despite scan findings.")
def admin_knowledge_approve_cmd(
    import_id: str,
    title: str,
    dest: str | None,
    to_raw: bool,
    sync_label: str,
    force: bool,
) -> None:
    """Promote a quarantined paste into wiki or raw intake."""
    from company_brain.agents.admin.knowledge_paste import KnowledgePasteAgent

    config = load_config()
    result = KnowledgePasteAgent(config).approve(
        import_id=import_id,
        title=title,
        dest=dest,
        to_raw=to_raw,
        sync_label=sync_label,
        force=force,
    )
    click.echo(result)


def register(main: click.Group) -> None:
    main.add_command(admin)
