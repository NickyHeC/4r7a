"""Health and policy doctor CLI commands."""

from __future__ import annotations

import click


@click.group(invoke_without_command=True)
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


def register(main: click.Group) -> None:
    main.add_command(doctor)
