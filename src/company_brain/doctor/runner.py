"""Run doctors, print reports, enforce min-score."""

from __future__ import annotations

import json
import sys
from typing import Callable

import click

from company_brain.config import (
    resolve_llm_provider,
    resolve_mode,
    resolve_runtime,
    resolve_wiki_dir,
)
from company_brain.doctor.agents import run_agents_doctor
from company_brain.doctor.connect import run_connect_doctor
from company_brain.doctor.ops import run_ops_doctor
from company_brain.doctor.scoring import append_history, history_entry, new_fail_regressions
from company_brain.doctor.types import DoctorReport
from company_brain.doctor.naming import run_naming_doctor
from company_brain.doctor.wiki import run_wiki_doctor

DoctorFn = Callable[[], DoctorReport]

DOCTORS: dict[str, DoctorFn] = {
    "connect": run_connect_doctor,
    "agents": run_agents_doctor,
    "wiki": run_wiki_doctor,
    "ops": run_ops_doctor,
    "naming": run_naming_doctor,
}


def run_doctor(name: str) -> DoctorReport:
    fn = DOCTORS.get(name)
    if fn is None:
        raise ValueError(f"unknown doctor: {name}")
    return fn()


def run_doctors(names: list[str] | None = None) -> dict[str, DoctorReport]:
    keys = names or list(DOCTORS.keys())
    return {name: run_doctor(name) for name in keys}


def _status_style(status: str) -> tuple[str, str]:
    if status == "pass":
        return click.style("OK ", fg="green"), ""
    if status == "fail":
        return click.style("FAIL", fg="red"), "red"
    return click.style("WARN", fg="yellow"), "yellow"


def print_report(report: DoctorReport) -> None:
    click.secho(f"\n{report.name}  score={report.score}/100", bold=True)
    for check in report.checks:
        mark, fg = _status_style(check.status)
        line = f"  [{mark}] {check.check}: {check.message}"
        if fg:
            click.secho(line, fg=fg)
        else:
            click.echo(line)
        if check.hint and check.status != "pass":
            click.secho(f"         -> {check.hint}", fg="bright_black")


def print_env_banner() -> None:
    click.secho("company-brain doctor", bold=True)
    click.echo(f"  Mode:     {resolve_mode()}")
    click.echo(f"  Runtime:  {resolve_runtime()}")
    click.echo(f"  Wiki dir: {resolve_wiki_dir()}")
    click.echo(f"  LLM:      {resolve_llm_provider()}")


def run_and_print(
    names: list[str] | None = None,
    *,
    as_json: bool = False,
    min_score: int | None = None,
    record_history: bool = True,
    fail_on_regression: bool = False,
) -> int:
    reports = run_doctors(names)
    if as_json:
        payload = {
            "doctors": {name: report.to_dict() for name, report in reports.items()},
            "aggregate_score": min(r.score for r in reports.values()) if reports else 100,
        }
        click.echo(json.dumps(payload, indent=2))
    else:
        if names is None or "connect" in names:
            print_env_banner()
        for report in reports.values():
            print_report(report)

    aggregate = min(r.score for r in reports.values()) if reports else 100
    if record_history and not as_json:
        append_history(history_entry(reports))

    exit_code = 0
    if min_score is not None and aggregate < min_score:
        if not as_json:
            click.secho(
                f"\nAggregate score {aggregate} below --min-score {min_score}",
                fg="red",
            )
        exit_code = 1

    if fail_on_regression:
        regressions = new_fail_regressions(reports)
        if regressions:
            if not as_json:
                click.secho("\nNew fail regressions (not in baseline):", fg="red")
                for name, rules in regressions.items():
                    click.echo(f"  {name}: {', '.join(sorted(rules))}")
            exit_code = 1

    return exit_code


def main_exit(
    names: list[str] | None = None,
    **kwargs,
) -> None:
    code = run_and_print(names, **kwargs)
    if code:
        sys.exit(code)
