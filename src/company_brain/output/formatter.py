"""Converts Article models into Notion enhanced markdown."""

from __future__ import annotations

from company_brain.config import WikiConfig
from company_brain.notion import markdown as md
from company_brain.wiki.article import Article
from company_brain.wiki.taxonomy import get_type_config


def format_article(article: Article, wiki_config: WikiConfig) -> str:
    """Render an Article as Notion enhanced markdown.

    Uses the article type's configured structure to organize sections.
    Falls back to the article's raw content if no structure is configured.
    """
    type_config = get_type_config(article.type, wiki_config)
    parts: list[str] = []

    parts.append(md.heading(article.title, level=1))
    parts.append("")

    if article.metadata.get("preamble"):
        parts.append(article.metadata["preamble"])
        parts.append("")

    if article.content and not _has_structured_sections(article.content, type_config.structure):
        parts.append(article.content.strip())
    else:
        for section_name in type_config.structure:
            section_content = _extract_section(article.content, section_name)
            parts.append(md.heading(section_name, level=2))
            if section_content:
                parts.append(section_content.strip())
            else:
                parts.append("")
            parts.append("")

    if article.related:
        parts.append(md.heading("Related", level=2))
        for related_id in article.related:
            parts.append(md.bulleted(related_id))
        parts.append("")

    if article.sources:
        parts.append(md.heading("Sources", level=2))
        for source_id in article.sources:
            parts.append(md.bulleted(f"Entry: {source_id}"))

    return "\n".join(parts)


def format_section_page(label: str, description: str, *, icon: str = "") -> str:
    """Render a wiki section landing page."""
    parts: list[str] = []
    if icon:
        parts.append(md.callout(f"{md.bold(label)}: {description}", icon=icon))
    else:
        parts.append(md.heading(label, level=1))
        parts.append(description)
    parts.append("")
    parts.append(md.divider())
    parts.append("")
    parts.append("*Articles in this section will appear below as they are created.*")
    return "\n".join(parts)


def _has_structured_sections(content: str, structure: list[str]) -> bool:
    """Check if the content already uses the expected section headings."""
    if not content:
        return False
    lower_content = content.lower()
    matches = sum(1 for s in structure if f"## {s.lower()}" in lower_content)
    return matches >= len(structure) // 2


def _extract_section(content: str, section_name: str) -> str:
    """Pull content under a ## heading matching section_name."""
    if not content:
        return ""

    lines = content.splitlines()
    target = f"## {section_name}".lower()
    collecting = False
    section_lines: list[str] = []

    for line in lines:
        stripped = line.strip().lower()
        if stripped == target or stripped.startswith(target + " "):
            collecting = True
            continue
        if collecting and stripped.startswith("## "):
            break
        if collecting:
            section_lines.append(line)

    return "\n".join(section_lines).strip()
