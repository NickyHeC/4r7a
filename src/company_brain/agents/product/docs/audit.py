"""Docs Audit — compare public llms.txt / sitemap / docs to Product Features.

SDK: Neither (deterministic fetch + string match). Proprietary features stay internal.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import is_handled, mark_handled
from company_brain.agents.product.posthog.feature_match import parse_feature_titles
from company_brain.agents.product.shared.product_slack import product_notifier
from company_brain.agents.product.shared.workstream_config import (
    docs_base_url,
    docs_cfg,
    docs_proprietary_patterns,
)
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import UPDATE, read_wiki_page, write_wiki_page

WIKI_PATH = "product/docs/audit.md"
TITLE = "Docs Audit"
FEATURE_WIKI = "product/feature.md"
WRITE_MODE = UPDATE


class DocsAuditAgent(BaseAgent):
    """Overwrite the docs audit table; notify on new public gaps."""

    name = "docs_audit"
    WRITE_MODE = WRITE_MODE

    def run(self, *, force: bool = False, **kwargs: Any) -> dict[str, Any]:
        features = parse_feature_titles(read_wiki_page(FEATURE_WIKI))
        public_text, fetch_notes = _fetch_public_corpus()
        proprietary = docs_proprietary_patterns()

        public_gaps: list[str] = []
        internal_only: list[str] = []
        covered: list[str] = []
        for feature in features:
            if _is_proprietary(feature, proprietary):
                internal_only.append(feature)
                continue
            if _mentioned(feature, public_text):
                covered.append(feature)
            else:
                public_gaps.append(feature)

        new_gaps = [
            f for f in public_gaps if force or not is_handled(f"docs_audit:gap:{f}", "done")
        ]
        for f in new_gaps:
            mark_handled(f"docs_audit:gap:{f}", "done")

        body = render_docs_audit(
            covered=covered,
            public_gaps=public_gaps,
            internal_only=internal_only,
            fetch_notes=fetch_notes,
            base_url=docs_base_url(),
        )
        write_wiki_page(
            WIKI_PATH,
            TITLE,
            body,
            mode=WRITE_MODE,
            section="product",
            type_="report",
        )

        if new_gaps:
            lines = ["Public docs gaps (features missing from llms.txt/sitemap/docs):"]
            for f in new_gaps[:20]:
                lines.append(f"• {f}")
            if len(new_gaps) > 20:
                lines.append(f"• …and {len(new_gaps) - 20} more")
            product_notifier().emit(Signal(text="\n".join(lines), severity=ACTIONABLE))

        return {
            "wiki_path": WIKI_PATH,
            "covered": len(covered),
            "public_gaps": public_gaps,
            "new_gaps": new_gaps,
            "internal_only": len(internal_only),
        }


def _is_proprietary(feature: str, patterns: list[str]) -> bool:
    fl = feature.lower()
    return any(p in fl for p in patterns)


def _mentioned(feature: str, corpus: str) -> bool:
    if not corpus:
        return False
    fl = feature.lower()
    if fl in corpus.lower():
        return True
    # token overlap: require most significant words
    tokens = [t for t in re.split(r"[^a-z0-9]+", fl) if len(t) > 3]
    if not tokens:
        return False
    corpus_l = corpus.lower()
    hits = sum(1 for t in tokens if t in corpus_l)
    return hits >= max(1, (len(tokens) + 1) // 2)


def _fetch_public_corpus() -> tuple[str, list[str]]:
    base = docs_base_url()
    notes: list[str] = []
    if not base:
        notes.append("docs.base_url unset — skipped live fetch.")
        return "", notes

    cfg = docs_cfg()
    paths = [
        str(cfg.get("llms_txt_path") or "/llms.txt"),
        str(cfg.get("sitemap_path") or "/sitemap.xml"),
        str(cfg.get("docs_root_path") or "/docs"),
    ]
    chunks: list[str] = []
    for path in paths:
        url = urljoin(base + "/", path.lstrip("/"))
        try:
            resp = requests.get(url, timeout=20)
            if resp.ok:
                chunks.append(resp.text[:200_000])
                notes.append(f"Fetched {url} ({len(resp.text)} bytes).")
            else:
                notes.append(f"HTTP {resp.status_code} for {url}.")
        except requests.RequestException as exc:
            notes.append(f"Fetch failed for {url}: {exc}")
    return "\n".join(chunks), notes


def render_docs_audit(
    *,
    covered: list[str],
    public_gaps: list[str],
    internal_only: list[str],
    fetch_notes: list[str],
    base_url: str,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    lines = [
        f"_Updated {now:%Y-%m-%d %H:%M UTC}_",
        "",
        f"**Public base:** `{base_url or '(unset)'}`",
        "",
        "Compare internal Product Features to public llms.txt / sitemap / docs. "
        "Proprietary matches are intentionally internal — do not publish.",
        "",
    ]
    if fetch_notes:
        lines.append("## Fetch notes")
        lines.append("")
        for n in fetch_notes:
            lines.append(f"- {n}")
        lines.append("")

    lines.extend(["## Covered in public docs", ""])
    if covered:
        for f in covered:
            lines.append(f"- {f}")
    else:
        lines.append("_None matched._")
    lines.append("")

    lines.extend(["## Public gaps", ""])
    if public_gaps:
        for f in public_gaps:
            lines.append(f"- {f}")
    else:
        lines.append("_No public gaps._")
    lines.append("")

    lines.extend(["## Intentionally internal", ""])
    if internal_only:
        for f in internal_only:
            lines.append(f"- {f}")
    else:
        lines.append("_None flagged proprietary._")
    lines.append("")
    return "\n".join(lines)
