"""Tests for wiki naming migration helpers."""

from __future__ import annotations

import json
from pathlib import Path

from company_brain.wiki.name_migrate import (
    apply_migration,
    migrate_rel_path,
    migrate_specialist_key,
    migrate_title,
    plan_migration,
)
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


def test_migrate_rel_path_exact_and_prefix():
    assert migrate_rel_path("engineering/github/open-prs.md") == "engineering/github/open-pr.md"
    assert migrate_rel_path("finance/expense-reports/2026-01.md") == (
        "finance/expense-report/2026-01.md"
    )
    assert migrate_rel_path("operations/granola/daily/2026-06-30.md") == (
        "operations/granola/meeting/2026-06-30.md"
    )
    assert migrate_rel_path("admin/table-of-contents.md") == "admin/content-catalog.md"


def test_migrate_rel_path_employee_work_log():
    assert migrate_rel_path("alice/work_log/2026-Q1.md", volume="employee") == (
        "alice/work-log/2026-Q1.md"
    )


def test_migrate_title_patterns():
    assert migrate_title("Linear Stale Projects and Issues") == "Stale Audit"
    assert migrate_title("January 2026 Expense Report") == "January 2026 Expenses"
    assert migrate_title("Vendor — stripe-com") == "Stripe Com"
    assert migrate_title("Meeting notes — 2026-06-30") == "Meetings 2026-06-30"


def test_migrate_specialist_key():
    assert migrate_specialist_key("gmail_ingest") == "ingest"
    assert migrate_specialist_key("gmail_inbox_triage") == "inbox_triage"
    assert migrate_specialist_key("decision_propagate") == "decision_propagate"


def test_plan_and_apply_renames_wiki_files(tmp_path: Path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    store = LocalWikiStore(root=wiki)
    store.write(
        "engineering/github/open-prs.md",
        MarkdownDoc(
            frontmatter={"title": "Open PRs", "id": "open-prs"},
            body="# Open PRs\n\nSee [[finance/company-timeline.md]].\n",
        ),
    )
    store.write(
        "finance/company-timeline.md",
        MarkdownDoc(
            frontmatter={"title": "Company Timeline"},
            body="# Company Timeline\n\nDecisions live here.\n",
        ),
    )

    plan = plan_migration(company_store=store, employee_store=None, include_routing=False)
    assert len(plan.renames) == 2
    paths = {r.old_path: r.new_path for r in plan.renames}
    assert paths["engineering/github/open-prs.md"] == "engineering/github/open-pr.md"
    assert paths["finance/company-timeline.md"] == "operations/decisions/timeline.md"

    counts = apply_migration(plan, company_store=store, employee_store=None)
    assert counts["renamed"] == 2
    assert store.exists("engineering/github/open-pr.md")
    assert store.exists("operations/decisions/timeline.md")
    open_pr = store.read("engineering/github/open-pr.md")
    assert "operations/decisions/timeline.md" in open_pr.body
    assert open_pr.frontmatter.get("id") == "open-pr"


def test_apply_routing_specialist_keys(tmp_path: Path):
    wiki = tmp_path / "wiki"
    routing = wiki / "operations/gmail/routing/me"
    routing.mkdir(parents=True)
    record = {
        "message_id": "m1",
        "thread_id": "t1",
        "mailbox": "me",
        "triaged_at": "2026-06-30T12:00:00+00:00",
        "handled": {
            "gmail_ingest": "2026-06-30T12:01:00+00:00",
            "gmail_crm": "2026-06-30T12:02:00+00:00",
        },
    }
    (routing / "m1.json").write_text(json.dumps(record))

    store = LocalWikiStore(root=wiki)
    plan = plan_migration(company_store=store, employee_store=None, rewrite_links=False)
    assert plan.routing_updates

    apply_migration(plan, company_store=store, employee_store=None)
    updated = json.loads((routing / "m1.json").read_text())
    assert "ingest" in updated["handled"]
    assert "connection" in updated["handled"]
    assert "gmail_ingest" not in updated["handled"]


def test_plan_skips_when_target_exists(tmp_path: Path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    store = LocalWikiStore(root=wiki)
    store.write("engineering/github/open-prs.md", MarkdownDoc(body="# Open PRs\n"))
    store.write("engineering/github/open-pr.md", MarkdownDoc(body="# Open PRs canonical\n"))

    plan = plan_migration(company_store=store, employee_store=None, include_routing=False)
    assert not any(r.old_path.endswith("open-prs.md") for r in plan.renames)
    assert any("open-pr.md" in c for c in plan.conflicts)
