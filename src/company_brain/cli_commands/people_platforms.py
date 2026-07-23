"""People, Notion, install, and platform onboarding CLI commands."""

from __future__ import annotations

import sys

import click

from company_brain.config import load_config


@click.group()
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
    """Create an offboarding proposal for a member (ask only)."""
    from company_brain.agents.hr.employee_offboarding import EmployeeOffboardingAgent

    config = load_config()
    result = EmployeeOffboardingAgent(config).execute(member_key=member_key, reason=reason)
    click.echo(result)


@hr.command("confirm-offboard")
@click.argument("member_key")
@click.option("--reason", default="admin_confirm", help="Confirmation reason label.")
def hr_confirm_offboard(member_key: str, reason: str) -> None:
    """Admin-confirmed offboard: status departed, revoke bridge, schedule archive."""
    from company_brain.agents.hr.offboard_confirm import OffboardConfirmAgent

    config = load_config()
    result = OffboardConfirmAgent(config).execute(member_key=member_key, reason=reason)
    click.echo(result)


@hr.command("onboard")
@click.argument("member_key", required=False, default="")
@click.option("--seed", is_flag=True, help="Bootstrap from config/hr_seed.yaml.")
@click.option("--no-manager", is_flag=True, help="Skip starting hr_manager.")
@click.option("--no-linkedin", is_flag=True, help="Skip LinkedIn WebSearch pull.")
def hr_onboard(
    member_key: str,
    seed: bool,
    no_manager: bool,
    no_linkedin: bool,
) -> None:
    """Onboard from seed lists or a single member/roster key."""
    from company_brain.agents.hr.hr_onboarding import HrOnboardingAgent

    if not seed and not (member_key or "").strip():
        raise click.UsageError("Provide MEMBER_KEY or pass --seed")
    config = load_config()
    result = HrOnboardingAgent(config).execute(
        seed=seed,
        member_key=member_key,
        start_manager=not no_manager,
        pull_linkedin=not no_linkedin,
    )
    click.echo(result)


@hr.command("manager")
@click.option("--once", is_flag=True, help="Run a single manager pass then exit.")
@click.option("--force", is_flag=True, help="Force LinkedIn pull + archive due check.")
def hr_manager_cmd(once: bool, force: bool) -> None:
    """Start or run the persistent HR manager."""
    from company_brain.agents.hr.hr_manager import HrManager

    config = load_config()
    agent = HrManager(config)
    result = agent.execute(once=once or force, force=force)
    if once or force:
        click.echo(result)


@hr.command("status-watch")
@click.argument("member_key")
@click.option("--reason", default="status_watch", help="Signal reason label.")
def hr_status_watch(member_key: str, reason: str) -> None:
    """Ask admin whether a member/roster person has departed."""
    from company_brain.agents.hr.status_watch import StatusWatchAgent

    config = load_config()
    click.echo(StatusWatchAgent(config).execute(member_key=member_key, reason=reason))


@click.group()
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


@click.group()
def install() -> None:
    """Guided company-brain install (profile, credentials, foundation, onboard)."""


@install.command("profile")
@click.option("--interactive/--no-interactive", default=None, help="Prompt for decisions.")
@click.option("--runtime", type=click.Choice(["local", "cloud"]), default=None)
@click.option("--brain-repo-url", default=None, help="Private 4r7a clone URL.")
@click.option("--wiki-repo-url", default=None, help="Private company-wiki URL.")
@click.option("--disable-department", multiple=True, help="Disable a department.")
@click.option("--enable-department", multiple=True, help="Enable a department.")
@click.option("--disable-platform", multiple=True, help="Disable a platform.")
@click.option("--enable-platform", multiple=True, help="Enable a platform.")
@click.option("--notion-sync/--no-notion-sync", default=None)
@click.option("--employee-wiki/--no-employee-wiki", default=None)
@click.option("--wiki-git-backup/--no-wiki-git-backup", default=None)
@click.option("--bridge/--no-bridge", default=None)
@click.option("--show", is_flag=True, help="Print current profile and exit.")
def install_profile_cmd(
    interactive: bool | None,
    runtime: str | None,
    brain_repo_url: str | None,
    wiki_repo_url: str | None,
    disable_department: tuple[str, ...],
    enable_department: tuple[str, ...],
    disable_platform: tuple[str, ...],
    enable_platform: tuple[str, ...],
    notion_sync: bool | None,
    employee_wiki: bool | None,
    wiki_git_backup: bool | None,
    bridge: bool | None,
    show: bool,
) -> None:
    """Compile or update config/install_profile.yaml."""
    from company_brain.agents.admin.install_profile import (
        apply_profile_flags,
        load_install_profile,
        profile_summary,
        prompt_profile,
    )

    if show:
        click.echo(profile_summary(load_install_profile()))
        return

    flag_touch = any(
        [
            runtime,
            brain_repo_url is not None,
            wiki_repo_url is not None,
            disable_department,
            enable_department,
            disable_platform,
            enable_platform,
            notion_sync is not None,
            employee_wiki is not None,
            wiki_git_backup is not None,
            bridge is not None,
        ]
    )
    if interactive is True or (interactive is None and not flag_touch and sys.stdin.isatty()):
        profile = prompt_profile()
    else:
        profile = apply_profile_flags(
            runtime=runtime,
            brain_repo_url=brain_repo_url,
            wiki_repo_url=wiki_repo_url,
            disable_department=disable_department,
            enable_department=enable_department,
            disable_platform=disable_platform,
            enable_platform=enable_platform,
            notion_sync=notion_sync,
            employee_wiki=employee_wiki,
            wiki_git_backup=wiki_git_backup,
            bridge=bridge,
        )
        click.secho("Updated config/install_profile.yaml", fg="green")
    click.echo(profile_summary(profile))


@install.command("credentials")
def install_credentials_cmd() -> None:
    """Print credential/OAuth checklist for enabled platforms only."""
    from company_brain.agents.admin.install_credentials import format_checklist

    click.echo(format_checklist())


@install.command("foundation")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON report.")
@click.option(
    "--no-create-wiki-repo",
    is_flag=True,
    help="Do not auto-create missing company-wiki via gh.",
)
def install_foundation_cmd(as_json: bool, no_create_wiki_repo: bool) -> None:
    """Validate repos, Notion, and wiki_git readiness from the install profile."""
    import json as json_lib

    from company_brain.agents.admin.install_foundation import (
        format_foundation_report,
        run_foundation_checks,
    )
    from company_brain.runtime.fleet_gate import redeploy_instructions

    report = run_foundation_checks(create_wiki_repo=not no_create_wiki_repo)
    if as_json:
        click.echo(json_lib.dumps(report.to_dict(), indent=2))
    else:
        click.echo(format_foundation_report(report))
        cue = redeploy_instructions()
        if cue:
            click.secho("\n" + cue, fg="yellow")
    if not report.ok:
        raise SystemExit(1)


@install.command("verify")
def install_verify_cmd() -> None:
    """Run foundation checks + profile-scoped connect doctor hints."""
    from company_brain.agents.admin.install_foundation import (
        format_foundation_report,
        run_foundation_checks,
    )
    from company_brain.agents.admin.install_profile import load_install_profile
    from company_brain.doctor.connect import run_connect_doctor

    profile = load_install_profile()
    foundation = run_foundation_checks(profile)
    click.echo(format_foundation_report(foundation))
    report = run_connect_doctor(profile=profile)
    click.echo(f"# connect doctor ({report.name}) score={report.score}")
    for check in report.checks:
        click.echo(f"- [{check.status}] {check.check}: {check.message}")
        if check.hint and check.status != "pass":
            click.echo(f"    hint: {check.hint}")
    if not foundation.ok:
        raise SystemExit(1)


@install.command("onboard")
@click.option("--strict", is_flag=True, help="Stop department sequence on first failure.")
@click.option("--no-managers", is_flag=True, help="Skip starting persistent managers.")
@click.option("--skip-foundation-check", is_flag=True, help="Skip foundation gate.")
@click.option(
    "--confirm-cleanup",
    is_flag=True,
    help="Admin confirms cleanup checklist review (still no auto-delete).",
)
def install_onboard_cmd(
    strict: bool,
    no_managers: bool,
    skip_foundation_check: bool,
    confirm_cleanup: bool,
) -> None:
    """Run department onboarding in order (eng → ops → product → growth → finance → hr)."""
    from company_brain.agents.admin.install_orchestrator import InstallOrchestratorAgent

    if not confirm_cleanup:
        click.secho(
            "Note: cleanup deletion is never automatic. Pass --confirm-cleanup after the "
            "admin explicitly approves reviewing unused-platform removal on a private fork.",
            fg="yellow",
        )
    config = load_config()
    result = InstallOrchestratorAgent(config).execute(
        strict=strict,
        start_managers=not no_managers,
        skip_foundation_check=skip_foundation_check,
        confirm_cleanup=confirm_cleanup,
    )
    click.echo(result)


@install.command("status")
def install_status_cmd() -> None:
    """Show install progress state keys + profile summary."""
    from company_brain.agents.admin.install_orchestrator import read_install_states
    from company_brain.agents.admin.install_profile import load_install_profile, profile_summary

    click.echo(profile_summary(load_install_profile()))
    click.echo("")
    states = read_install_states()
    if not states:
        click.echo("No install:* state keys yet.")
        return
    for key in sorted(states):
        click.echo(f"{key}: {states[key]}")


@install.command("cleanup")
@click.option(
    "--confirm",
    is_flag=True,
    help="Required. Confirms admin reviewed cleanup; still prints checklist only.",
)
def install_cleanup_cmd(confirm: bool) -> None:
    """Print unused-platform cleanup checklist (never deletes files)."""
    from company_brain.agents.admin.install_orchestrator import cleanup_checklist

    if not confirm:
        click.secho(
            "Refusing to emit cleanup steps without --confirm "
            "(admin must explicitly approve reviewing deletions).",
            fg="red",
        )
        raise SystemExit(2)
    click.echo(cleanup_checklist())


@click.group("github")
def github_group() -> None:
    """GitHub platform commands."""


@github_group.group("onboarding")
def github_onboarding_group() -> None:
    """GitHub onboarding."""


@github_onboarding_group.command("run")
@click.option("--no-manager", is_flag=True, help="Skip starting github_manager.")
def github_onboarding_run(no_manager: bool) -> None:
    """Backfill GitHub wiki pages and hand off to github_manager."""
    from company_brain.agents.engineering.github.github_onboarding import GitHubOnboardingAgent

    config = load_config()
    click.echo(GitHubOnboardingAgent(config).execute(start_manager=not no_manager))


@click.group("linear")
def linear_group() -> None:
    """Linear platform commands."""


@linear_group.group("onboarding")
def linear_onboarding_group() -> None:
    """Linear onboarding."""


@linear_onboarding_group.command("run")
@click.option("--no-manager", is_flag=True, help="Skip starting linear_manager.")
def linear_onboarding_run(no_manager: bool) -> None:
    """Run Linear onboarding backfill."""
    from company_brain.agents.engineering.linear.linear_onboarding import LinearOnboardingAgent

    config = load_config()
    click.echo(LinearOnboardingAgent(config).execute(start_manager=not no_manager))


@click.group("gmail")
def gmail_group() -> None:
    """Gmail platform commands."""


@gmail_group.group("onboarding")
def gmail_onboarding_group() -> None:
    """Gmail onboarding."""


@gmail_onboarding_group.command("run")
@click.option("--no-manager", is_flag=True, help="Skip starting gmail managers.")
def gmail_onboarding_run(no_manager: bool) -> None:
    """Run Gmail onboarding backfill."""
    from company_brain.agents.operations.gmail.gmail_onboarding import GmailOnboardingAgent

    config = load_config()
    click.echo(GmailOnboardingAgent(config).execute(start_manager=not no_manager))


@click.group("granola")
def granola_group() -> None:
    """Granola platform commands."""


@granola_group.group("onboarding")
def granola_onboarding_group() -> None:
    """Granola onboarding."""


@granola_onboarding_group.command("run")
@click.option("--no-manager", is_flag=True, help="Skip starting meeting_watch.")
def granola_onboarding_run(no_manager: bool) -> None:
    """Run Granola onboarding backfill."""
    from company_brain.agents.operations.granola.granola_onboarding import GranolaOnboardingAgent

    config = load_config()
    click.echo(GranolaOnboardingAgent(config).execute(start_manager=not no_manager))


@click.group("finance")
def finance_group() -> None:
    """Finance department commands."""


@finance_group.group("onboarding")
def finance_onboarding_group() -> None:
    """Finance onboarding."""


@finance_onboarding_group.command("run")
@click.option("--no-managers", is_flag=True, help="Skip starting finance managers.")
@click.option("--start-month", default=None, help="Earliest YYYY-MM to backfill.")
def finance_onboarding_run(no_managers: bool, start_month: str | None) -> None:
    """Backfill expense/quarterly pages and start finance managers."""
    from company_brain.agents.finance.finance_onboarding import FinanceOnboardingAgent

    config = load_config()
    click.echo(
        FinanceOnboardingAgent(config).execute(
            start_managers=not no_managers,
            start_month=start_month,
        )
    )


def register(main: click.Group) -> None:
    main.add_command(hr)
    main.add_command(notion)
    main.add_command(install)
    main.add_command(github_group)
    main.add_command(linear_group)
    main.add_command(gmail_group)
    main.add_command(granola_group)
    main.add_command(finance_group)
