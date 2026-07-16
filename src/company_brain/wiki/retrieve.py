"""Hybrid lexical wiki retrieval (TF + IDF + title boost + age decay).

No embeddings — scores are derived at query time over Markdown pages.
Callers supply path/sync filters (Slack ACL, Notion teamspace, bridge ReadGate).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from company_brain.wiki.store import CONTROL_FILES, MarkdownDoc, WikiStore

AllowFn = Callable[[str, MarkdownDoc], bool]

TITLE_BOOST = 4.0
AGE_HALF_LIFE_DAYS = 90.0
MIN_TERM_LEN = 3


def tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"\W+", (text or "").lower()) if len(t) >= MIN_TERM_LEN]


def _parse_age_days(doc: MarkdownDoc, path: Path | None) -> float:
    """Days since last update; 0 if unknown/fresh."""
    fm = doc.frontmatter or {}
    for key in ("updated", "updated_at", "last_synced", "date"):
        raw = fm.get(key)
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - ts.astimezone(timezone.utc)
            return max(delta.total_seconds() / 86400.0, 0.0)
        except (ValueError, TypeError, OSError):
            continue
    if path is not None and path.exists():
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            delta = datetime.now(timezone.utc) - mtime
            return max(delta.total_seconds() / 86400.0, 0.0)
        except OSError:
            pass
    return 0.0


def _age_factor(age_days: float) -> float:
    """Exponential decay; half-life ``AGE_HALF_LIFE_DAYS``."""
    if age_days <= 0:
        return 1.0
    return 0.5 ** (age_days / AGE_HALF_LIFE_DAYS)


def _term_tf(terms: list[str], text: str) -> dict[str, float]:
    lower = text.lower()
    return {t: float(lower.count(t)) for t in terms}


def score_document(
    terms: list[str],
    *,
    title: str,
    body: str,
    idf: dict[str, float],
    age_days: float = 0.0,
) -> float:
    """Score one document against query terms."""
    if not terms:
        return 1.0 * _age_factor(age_days)
    title_tf = _term_tf(terms, title)
    body_tf = _term_tf(terms, body)
    raw = 0.0
    for t in terms:
        w = idf.get(t, 1.0)
        raw += TITLE_BOOST * title_tf.get(t, 0.0) * w
        raw += body_tf.get(t, 0.0) * w
    return raw * _age_factor(age_days)


def build_idf(docs_tokens: list[set[str]], terms: list[str]) -> dict[str, float]:
    """Simple smoothed IDF over the in-scope corpus."""
    n = max(len(docs_tokens), 1)
    idf: dict[str, float] = {}
    for t in terms:
        df = sum(1 for toks in docs_tokens if t in toks)
        idf[t] = math.log((n + 1) / (df + 1)) + 1.0
    return idf


def path_in_prefixes(rel_path: str, prefixes: list[str]) -> bool:
    rel = rel_path.strip().strip("/")
    if not rel:
        return False
    for pfx in prefixes:
        base = pfx.rstrip("/")
        if rel == base or rel.startswith(base + "/"):
            return True
    return False


def retrieve(
    query: str,
    *,
    store: WikiStore,
    allow: AllowFn | None = None,
    prefixes: list[str] | None = None,
    deny_prefixes: tuple[str, ...] = (),
    limit: int = 6,
    snippet_chars: int = 1200,
    exclude: str | None = None,
) -> list[dict[str, Any]]:
    """Return ranked wiki hits ``{rel_path, title, snippet, score, notion_page_id}``."""
    terms = tokenize(query)
    candidates: list[tuple[str, MarkdownDoc, Path | None]] = []

    for rel in store.list():
        name = rel.rsplit("/", 1)[-1]
        if name in CONTROL_FILES or not rel.endswith(".md"):
            continue
        if exclude and rel == exclude:
            continue
        if any(rel.startswith(p) for p in deny_prefixes):
            continue
        if prefixes is not None and not path_in_prefixes(rel, prefixes):
            continue
        try:
            doc = store.read(rel)
        except FileNotFoundError:
            continue
        if allow is not None and not allow(rel, doc):
            continue
        abspath = store.abspath(rel) if hasattr(store, "abspath") else None
        candidates.append((rel, doc, abspath if isinstance(abspath, Path) else None))

    docs_tokens: list[set[str]] = []
    for _rel, doc, _p in candidates:
        title = str(doc.frontmatter.get("title") or "")
        docs_tokens.append(set(tokenize(f"{title}\n{doc.body}")))
    idf = build_idf(docs_tokens, terms)

    hits: list[tuple[float, dict[str, Any]]] = []
    for rel, doc, path in candidates:
        name = rel.rsplit("/", 1)[-1]
        title = str(doc.frontmatter.get("title") or name)
        age = _parse_age_days(doc, path)
        score = score_document(
            terms,
            title=title,
            body=doc.body,
            idf=idf,
            age_days=age,
        )
        if score <= 0 and terms:
            continue
        notion_id = str(doc.frontmatter.get("notion_page_id") or "")
        hits.append(
            (
                score,
                {
                    "rel_path": rel,
                    "title": title,
                    "snippet": doc.body[:snippet_chars],
                    "score": score,
                    "notion_page_id": notion_id,
                },
            )
        )

    hits.sort(key=lambda row: (-row[0], row[1]["rel_path"]))
    return [row[1] for row in hits[:limit]]
