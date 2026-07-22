"""Heuristic match helpers: wiki Product Features ↔ PostHog flags/events."""

from __future__ import annotations

import re
from dataclasses import dataclass

_BULLET_TITLE = re.compile(r"^\s*[-*]\s+\*\*(.+?)\*\*", re.MULTILINE)
_COMMIT_PREFIX = re.compile(
    r"^(feat|feature|fix|chore|docs|refactor|test|ci|build|perf|style)(\(.+?\))?:\s*",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def parse_feature_titles(wiki_body: str) -> list[str]:
    """Extract feature titles from ``product/feature.md`` bullet lines."""
    titles: list[str] = []
    seen: set[str] = set()
    for match in _BULLET_TITLE.finditer(wiki_body or ""):
        title = match.group(1).strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        titles.append(title)
    return titles


def normalize_slug(text: str) -> str:
    """Normalize a feature title / flag key / event name for fuzzy containment."""
    cleaned = _COMMIT_PREFIX.sub("", (text or "").strip())
    cleaned = cleaned.lower().replace("_", "-").replace(" ", "-")
    cleaned = _NON_ALNUM.sub("-", cleaned).strip("-")
    return cleaned


def slug_tokens(slug: str) -> set[str]:
    return {t for t in slug.split("-") if len(t) >= 3}


@dataclass(frozen=True)
class MatchRow:
    feature: str
    feature_slug: str
    flag_keys: list[str]
    event_names: list[str]
    status: str  # matched | missing


@dataclass(frozen=True)
class OrphanRow:
    kind: str  # flag | event
    key: str


def match_features(
    features: list[str],
    flag_keys: list[str],
    event_names: list[str],
) -> tuple[list[MatchRow], list[OrphanRow]]:
    """Match wiki features to PostHog keys via slug containment / shared tokens."""
    flag_slugs = {k: normalize_slug(k) for k in flag_keys}
    event_slugs = {e: normalize_slug(e) for e in event_names}
    used_flags: set[str] = set()
    used_events: set[str] = set()
    rows: list[MatchRow] = []

    for feature in features:
        fslug = normalize_slug(feature)
        ftokens = slug_tokens(fslug)
        matched_flags: list[str] = []
        matched_events: list[str] = []

        for key, slug in flag_slugs.items():
            if _slugs_related(fslug, slug, ftokens, slug_tokens(slug)):
                matched_flags.append(key)
                used_flags.add(key)
        for name, slug in event_slugs.items():
            # Skip autocapture noise for orphan/match tables
            if name.startswith("$") and name not in {"$pageview", "$identify"}:
                continue
            if _slugs_related(fslug, slug, ftokens, slug_tokens(slug)):
                matched_events.append(name)
                used_events.add(name)

        status = "matched" if (matched_flags or matched_events) else "missing"
        rows.append(
            MatchRow(
                feature=feature,
                feature_slug=fslug,
                flag_keys=sorted(matched_flags),
                event_names=sorted(matched_events),
                status=status,
            )
        )

    orphans: list[OrphanRow] = []
    for key in flag_keys:
        if key not in used_flags:
            orphans.append(OrphanRow(kind="flag", key=key))
    for name in event_names:
        if name.startswith("$"):
            continue
        if name not in used_events:
            orphans.append(OrphanRow(kind="event", key=name))
    orphans.sort(key=lambda o: (o.kind, o.key.lower()))
    return rows, orphans


def _slugs_related(
    feature_slug: str,
    other_slug: str,
    feature_tokens: set[str],
    other_tokens: set[str],
) -> bool:
    if not feature_slug or not other_slug:
        return False
    if feature_slug == other_slug:
        return True
    if feature_slug in other_slug or other_slug in feature_slug:
        return True
    if feature_tokens and other_tokens and feature_tokens & other_tokens:
        # Require at least one meaningful shared token and reasonable overlap
        overlap = feature_tokens & other_tokens
        if len(overlap) >= 2:
            return True
        # Single token only if it's long / distinctive
        only = next(iter(overlap))
        return len(only) >= 5
    return False
