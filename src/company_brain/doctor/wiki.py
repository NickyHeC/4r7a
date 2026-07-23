"""Wiki doctor — MD-first / Notion mirror invariants."""

from __future__ import annotations

import re
from pathlib import Path

from company_brain.config import PROJECT_ROOT
from company_brain.doctor.types import CheckResult, DoctorReport

AGENTS_ROOT = PROJECT_ROOT / "src" / "company_brain" / "agents"
_NOTION_ALLOW = frozenset(
    {
        "operations/notion/db.py",
        "operations/notion/task_sync.py",
        "operations/notion/task_scanner.py",
        "operations/notion/sync_pull.py",
        "operations/notion/wiki_directive.py",
        "operations/notion/conflict_store.py",
        "operations/notion/conflict_resolution.py",
        "operations/notion/conflict_apply.py",
        "operations/notion/page_system.py",
        "operations/notion/deprecated_collector.py",
        "operations/notion/stale_review.py",
        "operations/notion/notion_onboarding.py",
        "operations/notion_manager.py",
        "employee_wiki/employee_wiki_onboarding.py",
        "admin/weave_notion.py",
    }
)
_WIKI_WRITE_RE = re.compile(
    r"(Path\([^)]*wiki|open\([^)]*wiki|\.write_text\([^)]*wiki|wiki_dir\s*/\s*)",
    re.IGNORECASE,
)
# Non-MD state under the wiki volume (JSON queues, not articles) — not a
# write_wiki_page path; must not sync to Notion.
_WIKI_WRITE_ALLOW = frozenset(
    {
        "growth/leads/queue.py",
    }
)


def _iter_agent_py_files() -> list[Path]:
    return sorted(AGENTS_ROOT.rglob("*.py"))


def run_wiki_doctor() -> DoctorReport:
    report = DoctorReport(name="wiki")

    notion_in_agents: list[str] = []
    for path in _iter_agent_py_files():
        rel = path.relative_to(AGENTS_ROOT).as_posix()
        if "shared/notion_pages.py" in path.as_posix() or rel in _NOTION_ALLOW:
            continue
        text = path.read_text()
        if "NotionClient" in text or "from company_brain.notion" in text:
            notion_in_agents.append(path.relative_to(AGENTS_ROOT).as_posix())

    if notion_in_agents:
        report.checks.append(
            CheckResult(
                "notion_direct_in_agents",
                "fail",
                f"Agents import Notion directly: {', '.join(notion_in_agents)}",
                "use write_wiki_page / read_wiki_page; NotionSync mirrors MD",
            )
        )
    else:
        report.checks.append(
            CheckResult(
                "notion_direct_in_agents",
                "pass",
                "Agents do not import NotionClient",
            )
        )

    wiki_bypass: list[str] = []
    for path in _iter_agent_py_files():
        if path.is_relative_to(PROJECT_ROOT / "src" / "company_brain" / "wiki"):
            continue
        rel = path.relative_to(AGENTS_ROOT).as_posix()
        if rel.endswith("wiki_crm.py") or rel in _WIKI_WRITE_ALLOW:
            continue
        text = path.read_text()
        if "write_wiki_page" in text or "read_wiki_page" in text:
            continue
        if _WIKI_WRITE_RE.search(text):
            wiki_bypass.append(rel)

    if wiki_bypass:
        report.checks.append(
            CheckResult(
                "wiki_write_bypass",
                "warn",
                f"Possible direct wiki writes: {', '.join(wiki_bypass[:6])}",
                "route writes through write_wiki_page",
            )
        )
    else:
        report.checks.append(
            CheckResult("wiki_write_bypass", "pass", "No direct wiki file writes in agents")
        )

    return report
