"""Parse and strip plain-text ``@wiki`` directives from Notion/MD page bodies.

Directives are not a bot identity — sync/edit watchers spot ``@wiki`` and act on
the **current page only**. See ``docs/plans/notion.md`` Session 3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Whole-line directive: "@wiki …"
_DIRECTIVE_LINE = re.compile(r"(?im)^[ \t]*@wiki\b[ \t]*(.*?)\s*$")
_MOVE_TO = re.compile(
    r"(?i)\bmove\s+(?:to\s+)?(?P<path>[a-z0-9_./\-]+\.md)\b"
    r"|\bmove\s*:\s*(?P<path2>[a-z0-9_./\-]+\.md)\b"
)
_MARK_EXTERNAL = re.compile(r"(?i)\b(?:mark\s+)?external\b")
_FILL = re.compile(r"(?i)\bfill\b")
_EXTERNAL_ONLY = re.compile(r"(?i)^\s*(?:mark\s+)?external\s*$")


@dataclass(frozen=True)
class WikiDirective:
    """One ``@wiki`` instruction on a page."""

    raw: str
    instruction: str
    move_to: str | None = None
    want_fill: bool = False
    mark_external: bool = False


def extract_directives(body: str) -> tuple[list[WikiDirective], str]:
    """Return ``(directives, body_without_directive_lines)``."""
    directives: list[WikiDirective] = []
    kept: list[str] = []
    for line in (body or "").splitlines():
        m = _DIRECTIVE_LINE.match(line)
        if m:
            directives.append(parse_instruction(m.group(1) or ""))
            continue
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    if cleaned:
        cleaned += "\n"
    return directives, cleaned


def parse_instruction(text: str) -> WikiDirective:
    instruction = (text or "").strip()
    move_to = None
    m = _MOVE_TO.search(instruction)
    if m:
        move_to = (m.group("path") or m.group("path2") or "").strip().lstrip("/")

    mark_external = bool(_MARK_EXTERNAL.search(instruction))
    explicit_fill = bool(_FILL.search(instruction))

    if _EXTERNAL_ONLY.match(instruction):
        want_fill = False
    elif explicit_fill:
        want_fill = True
    elif move_to and not explicit_fill:
        rest = _MOVE_TO.sub("", instruction).strip()
        rest = re.sub(r"(?i)\bmove\s*(?:to)?\b", "", rest).strip(" :")
        want_fill = bool(rest) and not _EXTERNAL_ONLY.match(rest)
    else:
        # Free-text instruction → fill
        want_fill = bool(instruction)

    return WikiDirective(
        raw=instruction,
        instruction=instruction,
        move_to=move_to or None,
        want_fill=want_fill,
        mark_external=mark_external,
    )


def has_wiki_directive(body: str) -> bool:
    return bool(_DIRECTIVE_LINE.search(body or ""))
