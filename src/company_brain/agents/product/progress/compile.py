"""Progress Compile — rough feature status from GitHub wiki + Linear projects.

Discord community chatter is evidence only (fuzzy title match / dedupe), not a
second source of truth.

SDK: Neither (deterministic read/compile). Does not reimplement PR/issue sync.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.product.posthog.feature_match import (
    normalize_slug,
    parse_feature_titles,
    slug_tokens,
)
from company_brain.wiki.publish import UPDATE, read_wiki_page, write_wiki_page

WIKI_PATH = "product/progress.md"
TITLE = "Product Progress"
FEATURE_WIKI = "product/feature.md"
OPEN_PR = "engineering/github/open-pr.md"
BRANCH_STATUS = "engineering/github/branch-status.md"
FEATURE_UPDATE = "engineering/github/feature-update.md"
FEATURE_REQUEST_LOG = "product/feature-request-log.md"
WRITE_MODE = UPDATE

STATUSES = ("shipped", "shipping", "in_progress", "exploring", "unknown")
FUZZY_TOKEN_OVERLAP = 0.5


class ProgressCompileAgent(BaseAgent):
    """Overwrite Product Progress with a rough multi-source status table."""

    name = "progress_compile"
    WRITE_MODE = WRITE_MODE

    def run(self, *, force: bool = False, **kwargs: Any) -> dict[str, Any]:
        features = parse_feature_titles(read_wiki_page(FEATURE_WIKI))
        github = {
            "open_pr": read_wiki_page(OPEN_PR) or "",
            "branch_status": read_wiki_page(BRANCH_STATUS) or "",
            "feature_update": read_wiki_page(FEATURE_UPDATE) or "",
        }
        linear_projects = _linear_project_stats()
        discord_titles = extract_discord_feature_titles(read_wiki_page(FEATURE_REQUEST_LOG) or "")
        rows = compile_progress_rows(
            features,
            github=github,
            linear_projects=linear_projects,
            discord_titles=discord_titles,
        )
        body = render_progress(rows, linear_projects=linear_projects)
        write_wiki_page(
            WIKI_PATH,
            TITLE,
            body,
            mode=WRITE_MODE,
            section="product",
            type_="report",
        )
        return {
            "wiki_path": WIKI_PATH,
            "features": len(rows),
            "linear_projects": len(linear_projects),
            "discord_evidence": sum(1 for r in rows if r.get("discord")),
        }


def _linear_project_stats() -> list[dict[str, Any]]:
    try:
        from company_brain.agents.engineering.linear import linear_client as lc
    except Exception:
        return []
    try:
        issues = lc.list_issues(first=200)
    except Exception:
        return []

    by_project: dict[str, dict[str, int]] = defaultdict(lambda: {"done": 0, "total": 0})
    for issue in issues:
        project = issue.get("project") or {}
        name = str(project.get("name") or "").strip() or "(no project)"
        state = issue.get("state") or {}
        state_type = str(state.get("type") or "").lower()
        by_project[name]["total"] += 1
        if state_type in {"completed", "canceled"}:
            by_project[name]["done"] += 1

    out: list[dict[str, Any]] = []
    for name, counts in sorted(by_project.items()):
        total = counts["total"]
        done = counts["done"]
        ratio = (done / total) if total else 0.0
        out.append(
            {
                "name": name,
                "done": done,
                "total": total,
                "ratio": ratio,
                "status": _status_from_ratio(ratio, total),
            }
        )
    return out


def _status_from_ratio(ratio: float, total: int) -> str:
    if total <= 0:
        return "unknown"
    if ratio >= 0.95:
        return "shipped"
    if ratio >= 0.6:
        return "shipping"
    if ratio >= 0.15:
        return "in_progress"
    return "exploring"


def _github_signal(feature: str, github: dict[str, str]) -> str:
    fl = feature.lower()
    corpus_shipping = (github.get("open_pr") or "") + "\n" + (github.get("branch_status") or "")
    corpus_shipped = github.get("feature_update") or ""
    if fl and fl in corpus_shipped.lower():
        return "shipping"
    if fl and fl in corpus_shipping.lower():
        return "in_progress"
    # partial token match
    tokens = [t for t in re.split(r"[^a-z0-9]+", fl) if len(t) > 3]
    if tokens and any(t in corpus_shipping.lower() for t in tokens):
        return "in_progress"
    if tokens and any(t in corpus_shipped.lower() for t in tokens):
        return "shipping"
    return "unknown"


def _match_linear(feature: str, projects: list[dict[str, Any]]) -> dict[str, Any] | None:
    fl = feature.lower()
    for p in projects:
        name = str(p.get("name") or "").lower()
        if not name or name == "(no project)":
            continue
        if name in fl or fl in name:
            return p
        tokens = [t for t in re.split(r"[^a-z0-9]+", fl) if len(t) > 3]
        if tokens and all(t in name for t in tokens[:2]):
            return p
    return None


def _merge_status(gh: str, linear: str | None) -> str:
    rank = {s: i for i, s in enumerate(STATUSES)}
    candidates = [gh]
    if linear:
        candidates.append(linear)
    # prefer more advanced non-unknown
    known = [c for c in candidates if c != "unknown"]
    if not known:
        return "unknown"
    return min(known, key=lambda s: rank.get(s, 99))


def extract_discord_feature_titles(log_body: str) -> list[str]:
    """Pull feature-ish titles from the feature-request log (Discord evidence)."""
    titles: list[str] = []
    seen: set[str] = set()
    for line in (log_body or "").splitlines():
        # Discord / community lines often look like: - **Title** — ... or ### Title
        m = re.search(r"\*\*(.+?)\*\*", line)
        if not m:
            m = re.match(r"^#{2,3}\s+(.+)$", line.strip())
        if not m:
            continue
        title = m.group(1).strip()
        # Prefer lines that mention discord / community as evidence
        lower = line.lower()
        if "discord" not in lower and "community" not in lower and "feature request" not in lower:
            # still allow bold titles in the feature-request log
            if "feature-request" not in (log_body[:200].lower()):
                pass
        slug = normalize_slug(title)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        titles.append(title)
    return titles


def titles_fuzzy_match(a: str, b: str) -> bool:
    """Deterministic fuzzy title match (normalize + token overlap)."""
    sa, sb = normalize_slug(a), normalize_slug(b)
    if not sa or not sb:
        return False
    if sa == sb or sa in sb or sb in sa:
        return True
    ta, tb = slug_tokens(sa), slug_tokens(sb)
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / max(len(ta), len(tb))
    return overlap >= FUZZY_TOKEN_OVERLAP


def dedupe_feature_list(features: list[str]) -> list[str]:
    """Collapse near-duplicate feature titles; keep first canonical name."""
    kept: list[str] = []
    for feat in features:
        if any(titles_fuzzy_match(feat, k) for k in kept):
            continue
        kept.append(feat)
    return kept


def compile_progress_rows(
    features: list[str],
    *,
    github: dict[str, str],
    linear_projects: list[dict[str, Any]],
    discord_titles: list[str] | None = None,
) -> list[dict[str, Any]]:
    discord_titles = discord_titles or []
    # Collapse near-duplicates among product features first
    features = dedupe_feature_list(features)
    rows: list[dict[str, Any]] = []
    for feature in features:
        gh = _github_signal(feature, github)
        proj = _match_linear(feature, linear_projects)
        linear_status = str(proj["status"]) if proj else None
        status = _merge_status(gh, linear_status)
        discord_hits = [t for t in discord_titles if titles_fuzzy_match(feature, t)]
        # Discord is evidence only — never changes status SoT
        rows.append(
            {
                "feature": feature,
                "status": status,
                "github": gh,
                "linear_project": proj["name"] if proj else "—",
                "linear_done": f"{proj['done']}/{proj['total']}" if proj else "—",
                "discord": ", ".join(discord_hits[:3]) if discord_hits else "—",
            }
        )
    return rows


def render_progress(
    rows: list[dict[str, Any]],
    *,
    linear_projects: list[dict[str, Any]],
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    lines = [
        f"_Updated {now:%Y-%m-%d %H:%M UTC}_",
        "",
        "Rough status only — GitHub wiki signals + Linear project completion. "
        "Discord / community feature-request titles are evidence citations only "
        "(fuzzy-matched; never a second SoT).",
        "",
        "## Features",
        "",
    ]
    if not rows:
        lines.append("_No features in Product Features yet._\n")
    else:
        lines.extend(
            [
                "| Feature | Status | GitHub | Linear | Done/Total | Discord evidence |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in rows:
            lines.append(
                f"| {row['feature']} | `{row['status']}` | `{row['github']}` | "
                f"{row['linear_project']} | {row['linear_done']} | "
                f"{row.get('discord') or '—'} |"
            )
        lines.append("")

    lines.extend(["## Linear projects", ""])
    if not linear_projects:
        lines.append("_No Linear issues readable (missing key or empty)._")
    else:
        lines.extend(["| Project | Status | Done/Total |", "| --- | --- | --- |"])
        for p in linear_projects:
            lines.append(f"| {p['name']} | `{p['status']}` | {p['done']}/{p['total']} |")
    lines.append("")
    return "\n".join(lines)
