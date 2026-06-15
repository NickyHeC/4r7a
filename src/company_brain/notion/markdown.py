"""Helpers for building Notion enhanced markdown content."""

from __future__ import annotations


def heading(text: str, level: int = 1, *, color: str | None = None) -> str:
    prefix = "#" * min(max(level, 1), 4)
    color_attr = f' {{color="{color}"}}' if color else ""
    return f"{prefix} {text}{color_attr}"


def callout(text: str, *, icon: str = "💡", color: str = "blue_bg") -> str:
    return f'<callout icon="{icon}" color="{color}">\n\t{text}\n</callout>'


def toggle(summary: str, children: str) -> str:
    indented = "\n".join(f"\t{line}" for line in children.splitlines())
    return f"<details>\n<summary>{summary}</summary>\n{indented}\n</details>"


def todo(text: str, *, checked: bool = False) -> str:
    marker = "[x]" if checked else "[ ]"
    return f"- {marker} {text}"


def bulleted(text: str) -> str:
    return f"- {text}"


def numbered(text: str, n: int = 1) -> str:
    return f"{n}. {text}"


def divider() -> str:
    return "---"


def mention_page(url: str, title: str) -> str:
    return f'<mention-page url="{url}">{title}</mention-page>'


def mention_date(start: str, *, end: str | None = None) -> str:
    if end:
        return f'<mention-date start="{start}" end="{end}"/>'
    return f'<mention-date start="{start}"/>'


def bold(text: str) -> str:
    return f"**{text}**"


def italic(text: str) -> str:
    return f"*{text}*"


def code_inline(text: str) -> str:
    return f"`{text}`"


def code_block(code: str, language: str = "") -> str:
    return f"```{language}\n{code}\n```"


def table(headers: list[str], rows: list[list[str]]) -> str:
    """Build a simple markdown table (Notion renders these natively)."""
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def page_link(page_id: str, title: str) -> str:
    """Notion page mention by ID (will be resolved by Notion)."""
    url = f"https://www.notion.so/{page_id.replace('-', '')}"
    return mention_page(url, title)


def build_article_page(
    title: str,
    sections: dict[str, str],
    *,
    icon: str | None = None,
    preamble: str | None = None,
) -> str:
    """Assemble a full article page from title and named sections.

    Each key in `sections` becomes an ## heading, value is the body text.
    """
    parts: list[str] = []
    parts.append(heading(title, level=1))

    if preamble:
        parts.append("")
        parts.append(preamble)

    for section_title, body in sections.items():
        parts.append("")
        parts.append(heading(section_title, level=2))
        if body.strip():
            parts.append(body.strip())

    return "\n".join(parts)
