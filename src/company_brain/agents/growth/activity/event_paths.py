"""Wiki paths and slug helpers for company activity events."""

from __future__ import annotations

import re

EVENT_DIR = "growth/activity/event"
INDEX_PATH = "growth/activity/_index.md"
INDEX_TITLE = "Company Activity"


def slugify_event(name: str) -> str:
    text = (name or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:80] or "event"


def event_rel_path(slug: str) -> str:
    return f"{EVENT_DIR}/{slug}.md"


def event_title(name: str) -> str:
    return (name or "Event").strip() or "Event"
