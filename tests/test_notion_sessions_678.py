"""Tests for Notion Sessions 6–8: archive/stale, onboarding, manager coherence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from company_brain.agents.operations.notion.deprecated_collector import DeprecatedCollectorAgent
from company_brain.agents.operations.notion.notion_onboarding import NotionOnboardingAgent
from company_brain.agents.operations.notion.stale_review import StaleReviewAgent
from company_brain.agents.operations.notion_manager import NotionManager
from company_brain.config import AppConfig, NotionConfig, load_config
from company_brain.notion.archive_policy import archive_eligibility, is_stale_candidate
from company_brain.notion.discovery import DiscoveredPage, DiscoveryReport
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


def _cfg(**kwargs) -> AppConfig:
    notion = NotionConfig(
        root_page_id="root-page",
        teamspaces={"admin": "admin-parent", "company": "company-parent"},
        archive_parents={"admin": "admin-archive", "company": "company-archive"},
        section_teamspace={"admin": "admin", "operations": "company"},
        mirror_enabled=True,
        **kwargs,
    )
    return AppConfig(wiki=load_config().wiki, notion=notion)


def _past(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_archive_requires_all_conditions():
    now = datetime.now(timezone.utc)
    fm = {
        "status": "done",
        "last_updated": _past(40),
        "shared_link": False,
    }
    # Missing notion idle
    d = archive_eligibility(
        fm,
        notion_last_edited=_past(5),
        idle_days=30,
        now=now,
    )
    assert d.eligible is False
    assert "notion_recent_or_unknown" in d.reasons

    d2 = archive_eligibility(
        fm,
        notion_last_edited=_past(40),
        idle_days=30,
        now=now,
    )
    assert d2.eligible is True


def test_archive_fails_without_done():
    d = archive_eligibility(
        {"last_updated": _past(40), "shared_link": False},
        notion_last_edited=_past(40),
        idle_days=30,
    )
    assert d.eligible is False
    assert "not_done" in d.reasons


def test_archive_fails_closed_on_unknown_share():
    d = archive_eligibility(
        {"status": "done", "last_updated": _past(40)},
        notion_last_edited=_past(40),
        idle_days=30,
    )
    assert d.eligible is False
    assert "shared_link_or_unknown" in d.reasons


def test_stale_candidate_active_idle():
    assert is_stale_candidate({"last_updated": _past(100)}, stale_days=90) is True
    done = {"last_updated": _past(100), "status": "done"}
    assert is_stale_candidate(done, stale_days=90) is False
    assert is_stale_candidate({"last_updated": _past(10)}, stale_days=90) is False


def test_deprecated_collector_archives(tmp_path):
    store = LocalWikiStore(root=tmp_path)
    store.write(
        "operations/old-plan.md",
        MarkdownDoc(
            frontmatter={
                "title": "Old Plan",
                "section": "operations",
                "status": "done",
                "last_updated": _past(45),
                "shared_link": False,
                "notion_page_id": "page-1",
            },
            body="# Old Plan\n\nShipped.\n",
        ),
    )
    client = MagicMock()
    client.is_installed.return_value = True
    client.check_auth.return_value = True
    client.get_page_meta.return_value = {"last_edited_time": _past(45)}
    client.api.return_value = MagicMock()

    with patch(
        "company_brain.agents.operations.notion.deprecated_collector.platform_config.archive_idle_days",
        return_value=30,
    ):
        result = DeprecatedCollectorAgent(_cfg(), store=store, client=client).run()
    assert result["archived"] == 1
    doc = store.read("operations/old-plan.md")
    assert doc.frontmatter.get("archived") is True
    client.api.assert_called()


def test_deprecated_collector_skips_incomplete(tmp_path):
    store = LocalWikiStore(root=tmp_path)
    store.write(
        "operations/live.md",
        MarkdownDoc(
            frontmatter={
                "title": "Live",
                "status": "done",
                "last_updated": _past(45),
                # no shared_link confirmation
                "notion_page_id": "page-2",
            },
            body="# Live\n",
        ),
    )
    client = MagicMock()
    client.is_installed.return_value = True
    client.check_auth.return_value = True
    client.get_page_meta.return_value = {"last_edited_time": _past(45)}
    with patch(
        "company_brain.agents.operations.notion.deprecated_collector.platform_config.archive_idle_days",
        return_value=30,
    ):
        result = DeprecatedCollectorAgent(_cfg(), store=store, client=client).run()
    assert result["archived"] == 0
    assert store.read("operations/live.md").frontmatter.get("archived") is not True


def test_stale_review_flags(tmp_path):
    store = LocalWikiStore(root=tmp_path)
    store.write(
        "operations/aging.md",
        MarkdownDoc(
            frontmatter={
                "title": "Aging",
                "section": "operations",
                "last_updated": _past(120),
            },
            body="# Aging\n\nStill open.\n",
        ),
    )
    with patch(
        "company_brain.agents.operations.notion.stale_review.platform_config.stale_idle_days",
        return_value=90,
    ):
        result = StaleReviewAgent(_cfg(), store=store, client=MagicMock(), sync=False).run()
    assert result["flagged"] == 1
    assert store.exists("operations/notion/review.md")
    assert store.read("operations/aging.md").frontmatter.get("stale_reviewed") is True


def test_onboarding_ingest_only_without_confirm(tmp_path, monkeypatch):
    store = LocalWikiStore(root=tmp_path)
    client = MagicMock()
    client.is_installed.return_value = True
    client.check_auth.return_value = True
    client.get_page_markdown.return_value = ("# Existing\n\nBody from Notion.\n", None)

    report = DiscoveryReport(
        workspace_id="ws",
        pages=[
            DiscoveredPage(
                page_id="p1",
                title="Existing Doc",
                parent_id=None,
                parent_type="workspace",
                last_edited=_past(1),
            )
        ],
        databases=[],
        groups=[],
        total_pages=1,
        total_databases=0,
        scanned_at=_past(0),
    )

    cfg = _cfg()
    monkeypatch.setattr(
        "company_brain.agents.operations.notion.notion_onboarding.scan_workspace",
        lambda *a, **k: report,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.notion.notion_onboarding.load_notion_config",
        lambda: cfg.notion,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.notion.notion_onboarding.save_notion_config",
        lambda c: None,
    )

    agent = NotionOnboardingAgent(cfg, store=store, client=client)
    result = agent.run(confirm_mirror=False, start_manager=False, ingest_existing=True)
    assert result["mirror_enabled"] is False
    assert result["ingested"] == 1
    # Find ingested file
    paths = [p for p in store.list() if "existing" in p.lower() or p.endswith(".md")]
    assert any(store.read(p).frontmatter.get("ingested_from_notion") for p in paths)


def test_onboarding_builds_structure_when_empty(tmp_path, monkeypatch):
    store = LocalWikiStore(root=tmp_path)
    client = MagicMock()
    client.is_installed.return_value = True
    client.check_auth.return_value = True
    client.search_all_pages.return_value = []
    client.create_page.return_value = MagicMock(json_data={"id": "new-page"}, stdout="")

    report = DiscoveryReport(
        workspace_id="ws",
        pages=[],
        databases=[],
        groups=[],
        total_pages=0,
        total_databases=0,
        scanned_at=_past(0),
    )
    cfg = _cfg()
    monkeypatch.setattr(
        "company_brain.agents.operations.notion.notion_onboarding.scan_workspace",
        lambda *a, **k: report,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.notion.notion_onboarding.load_notion_config",
        lambda: cfg.notion,
    )
    saved: list = []
    monkeypatch.setattr(
        "company_brain.agents.operations.notion.notion_onboarding.save_notion_config",
        lambda c: saved.append(c),
    )

    agent = NotionOnboardingAgent(cfg, store=store, client=client)
    result = agent.run(confirm_mirror=False, start_manager=False)
    assert result["mirror_enabled"] is True
    assert result["structure"]
    assert "archive:company" in result["structure"]


def test_manager_run_once_includes_crm_and_weave(tmp_path):
    cfg = _cfg()
    client = MagicMock()
    client.is_installed.return_value = True
    client.check_auth.return_value = True
    mgr = NotionManager(cfg)
    mgr._client = client

    with (
        patch.object(mgr, "_run_agent", return_value={"ok": True}) as run_agent,
        patch.object(mgr, "_run_callable", side_effect=lambda label, fn: {label: True}) as run_call,
    ):
        results = mgr.run_once()
    assert "sync_pull" in results
    assert "stale_review" in results
    assert "deprecated_collector" in results
    assert "crm_sync" in results
    assert "weave_approvals" in results
    assert run_agent.called
    assert run_call.called
