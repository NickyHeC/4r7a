"""Hiring Log — append roster / member HR events to the wiki.

Tracks trial, intern, contractor, and W2 join / promote / depart.

SDK: Neither (wiki writes).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.wiki.publish import APPEND, format_append_section, write_wiki_page

WIKI_PATH = "hr/hiring-log.md"
TITLE = "Hiring Log"


class HiringLogAgent(BaseAgent):
    """Append HR events to the hiring log."""

    name = "hiring_log"
    WRITE_MODE = APPEND

    def run(
        self,
        *,
        heading: str,
        body: str,
        trigger: str = "hr",
        why: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        section = format_append_section(
            heading or stamp,
            body,
            trigger=trigger,
            why=why,
        )
        write_wiki_page(
            WIKI_PATH,
            TITLE,
            section,
            mode=self.WRITE_MODE,
            section="hr",
            type_="log",
        )
        return {"status": "ok", "wiki_path": WIKI_PATH}


def append_hiring_log(heading: str, body: str, *, trigger: str, why: str = "") -> None:
    from company_brain.config import load_config

    HiringLogAgent(load_config()).run(heading=heading, body=body, trigger=trigger, why=why)


def backfill_hire_entry(
    *,
    key: str,
    employment_type: str,
    department: str = "",
    email: str = "",
    start_date: str = "",
    end_date: str = "",
    notes: str = "",
) -> None:
    """Append a historical hire row (used by hr_onboarding seed backfill)."""
    lines = [
        f"- **Key:** `{key}`",
        f"- **Employment type:** {employment_type or '—'}",
        f"- **Department:** {department or '—'}",
        f"- **Email:** {email or '—'}",
        f"- **Start:** {start_date or '—'}",
    ]
    if end_date:
        lines.append(f"- **End:** {end_date}")
    if notes:
        lines.append(f"- **Notes:** {notes}")
    heading = f"Past hire — {key}"
    if start_date:
        heading = f"Past hire — {key} ({start_date})"
    append_hiring_log(
        heading,
        "\n".join(lines),
        trigger="hr_onboarding_backfill",
        why=key,
    )


def join_hire_entry(
    *,
    key: str,
    employment_type: str,
    department: str = "",
    email: str = "",
    start_date: str = "",
    linkedin_url: str = "",
) -> None:
    lines = [
        f"- **Key:** `{key}`",
        f"- **Employment type:** {employment_type or '—'}",
        f"- **Department:** {department or '—'}",
        f"- **Email:** {email or '—'}",
        f"- **Start:** {start_date or datetime.now(timezone.utc).date().isoformat()}",
    ]
    if linkedin_url:
        lines.append(f"- **LinkedIn:** {linkedin_url}")
    append_hiring_log(
        f"Joined — {key}",
        "\n".join(lines),
        trigger="hr_onboarding",
        why=key,
    )
