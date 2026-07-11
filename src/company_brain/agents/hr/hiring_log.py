"""Hiring Log — append roster promotions and HR events to the wiki.

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
