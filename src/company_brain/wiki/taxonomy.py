"""Company wiki taxonomy: section definitions and classification helpers."""

from __future__ import annotations

from company_brain.config import ArticleTypeConfig, SectionConfig, WikiConfig

CLASSIFICATION_KEYWORDS: dict[str, list[str]] = {
    "team": ["team", "squad", "group", "department", "org"],
    "person": ["people", "staff", "employee", "directory", "who"],
    "project": ["project", "initiative", "program", "milestone"],
    "product": ["product", "feature", "roadmap", "release", "spec"],
    "architecture": [
        "architecture",
        "adr",
        "design",
        "system",
        "infrastructure",
        "tech stack",
    ],
    "process": ["process", "procedure", "workflow", "sop", "how we"],
    "decision": ["decision", "rfc", "proposal", "tradeoff"],
    "runbook": ["runbook", "playbook", "incident", "on-call", "alert"],
    "onboarding": ["onboarding", "new hire", "setup", "getting started", "orientation"],
    "policy": ["policy", "compliance", "security", "guideline", "rule"],
    "vendor": ["vendor", "tool", "service", "integration", "contract"],
    "meeting": ["meeting", "standup", "retro", "sync", "minutes"],
    "postmortem": ["postmortem", "post-mortem", "rca", "incident review", "lessons learned"],
    "guide": ["guide", "how-to", "tutorial", "walkthrough", "best practice"],
    "term": ["glossary", "definition", "terminology", "acronym"],
}


def classify_title(title: str) -> str | None:
    """Attempt to classify a page title into an article type.

    Returns the article type string or None if no confident match.
    """
    lower = title.lower()
    scores: dict[str, int] = {}
    for article_type, keywords in CLASSIFICATION_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in lower)
        if score > 0:
            scores[article_type] = score

    if not scores:
        return None
    return max(scores, key=scores.get)  # type: ignore[arg-type]


def get_all_article_types(wiki_config: WikiConfig) -> list[str]:
    """Return all article type keys from the taxonomy."""
    return list(wiki_config.article_types.keys())


def get_section_for_article_type(article_type: str, wiki_config: WikiConfig) -> str | None:
    """Return the section key that houses a given article type."""
    return wiki_config.get_section_for_type(article_type)


def get_section_config(section_key: str, wiki_config: WikiConfig) -> SectionConfig | None:
    return wiki_config.sections.get(section_key)


def get_type_config(article_type: str, wiki_config: WikiConfig) -> ArticleTypeConfig:
    return wiki_config.get_type_config(article_type)
