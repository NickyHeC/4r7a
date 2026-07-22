"""Progress Compile — rough feature status from GitHub wiki + Linear projects.

SDK: Neither (deterministic read/compile). Does not reimplement PR/issue sync.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.product.posthog.feature_match import parse_feature_titles
from company_brain.wiki.publish import UPDATE, read_wiki_page, write_wiki_page

WIKI_PATH = "product/progress.md"
TITLE = "Product Progress"
FEATURE_WIKI = "product/feature.md"
OPEN_PR = "engineering/github/open-pr.md"
BRANCH_STATUS = "engineering/github/branch-status.md"
FEATURE_UPDATE = "engineering/github/feature-update.md"
WRITE_MODE = UPDATE

STATUSES = ("shipped", "shipping", "in_progress", "exploring", "unknown")


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
        rows = compile_progress_rows(features, github=github, linear_projects=linear_projects)
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


def compile_progress_rows(
    features: list[str],
    *,
    github: dict[str, str],
    linear_projects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature in features:
        gh = _github_signal(feature, github)
        proj = _match_linear(feature, linear_projects)
        linear_status = str(proj["status"]) if proj else None
        status = _merge_status(gh, linear_status)
        rows.append(
            {
                "feature": feature,
                "status": status,
                "github": gh,
                "linear_project": proj["name"] if proj else "—",
                "linear_done": f"{proj['done']}/{proj['total']}" if proj else "—",
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
        "Rough status only — combines GitHub wiki signals (open PRs, branches, "
        "feature updates) with Linear project completion. Not a precise %. ",
        "",
        "## Features",
        "",
    ]
    if not rows:
        lines.append("_No features in Product Features yet._\n")
    else:
        lines.extend(
            [
                "| Feature | Status | GitHub signal | Linear project | Done/Total |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for row in rows:
            lines.append(
                f"| {row['feature']} | `{row['status']}` | `{row['github']}` | "
                f"{row['linear_project']} | {row['linear_done']} |"
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
