"""Tests for investor newsletter + knowledge paste admin operators."""

from __future__ import annotations

from pathlib import Path

import pytest

from company_brain.agents.admin.investor_newsletter import (
    InvestorNewsletterAgent,
    gather_investor_evidence,
)
from company_brain.agents.admin.knowledge_paste import (
    KnowledgePasteAgent,
    is_untrusted_wiki_path,
)
from company_brain.config import load_config
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


@pytest.fixture()
def wiki_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    return wiki


@pytest.fixture(autouse=True)
def _quiet_admin_notify(monkeypatch: pytest.MonkeyPatch) -> None:
    class _N:
        def emit(self, *args, **kwargs):
            return False

    monkeypatch.setattr(
        "company_brain.agents.admin.knowledge_paste.wiki_admin_notifier",
        lambda: _N(),
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.investor_newsletter.wiki_admin_notifier",
        lambda: _N(),
    )


def test_untrusted_paths() -> None:
    assert is_untrusted_wiki_path("admin/knowledge/note.md")
    assert is_untrusted_wiki_path("external/foo/bar.md")
    assert is_untrusted_wiki_path("raw/entries/x.md")
    assert not is_untrusted_wiki_path("admin/install-progress.md")
    assert not is_untrusted_wiki_path("engineering/github/open-pr.md")


def test_knowledge_paste_quarantine_and_promote(wiki_tmp: Path) -> None:
    agent = KnowledgePasteAgent(load_config())
    result = agent.run(
        title="Bookface Note",
        body="# Hello\n\nUseful thread summary.\n",
        approve=True,
    )
    assert result["status"] == "promoted"
    assert "import_id" in result
    store = LocalWikiStore(root=wiki_tmp)
    assert store.exists("admin/knowledge/bookface-note.md")
    assert store.exists(f"admin/knowledge-review/{result['import_id']}.md")


def test_knowledge_paste_to_raw(
    wiki_tmp: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_dir = tmp_path / "raw"
    monkeypatch.setenv("COMPANY_BRAIN_RAW_DIR", str(raw_dir))
    agent = KnowledgePasteAgent(load_config())
    result = agent.run(
        title="Absorb Me",
        body="Insight worth absorbing.\n",
        to_raw=True,
        approve=True,
    )
    assert result["status"] == "promoted"
    assert result["promote"]["mode"] == "raw"
    entries = list((raw_dir / "entries").glob("*.md"))
    assert entries, "raw entry not written to resolve_raw_dir()/entries"
    text = entries[0].read_text()
    assert "source_type: admin_paste" in text


def test_knowledge_paste_company_dest(wiki_tmp: Path) -> None:
    agent = KnowledgePasteAgent(load_config())
    result = agent.run(
        title="Shared Insight",
        body="Company-wide note.\n",
        dest="operations/misc/shared-insight.md",
        sync_label="company",
        approve=True,
    )
    assert result["status"] == "promoted"
    store = LocalWikiStore(root=wiki_tmp)
    assert store.exists("operations/misc/shared-insight.md")
    doc = store.read("operations/misc/shared-insight.md")
    assert doc.frontmatter.get("sync") == "company"


def test_investor_newsletter_draft(wiki_tmp: Path) -> None:
    store = LocalWikiStore(root=wiki_tmp)
    store.write(
        "product/progress.md",
        MarkdownDoc(body="# Progress\n\n- Shipped onboarding\n- Improved retrieve\n"),
    )
    store.write(
        "engineering/github/feature-update.md",
        MarkdownDoc(body="# Feature Update\n\n## Week of 2026-07-01\n\n- wiki install\n"),
    )
    agent = InvestorNewsletterAgent(load_config())
    out = agent.run(month="2026-07", force=True, sync=False)
    assert out["status"] == "ok"
    assert store.exists("admin/investor-newsletter/2026-07.md")
    body = store.read("admin/investor-newsletter/2026-07.md").body
    assert "draft" in body.lower()
    assert "Investor Update" in body
    evidence = gather_investor_evidence("2026-07")
    assert "product/progress.md" in evidence["sources"]


def test_investor_verify_rejects_email(wiki_tmp: Path) -> None:
    store = LocalWikiStore(root=wiki_tmp)
    store.write(
        "product/feature.md",
        MarkdownDoc(body="- Feature A\n"),
    )
    agent = InvestorNewsletterAgent(load_config())
    # Force a body with email via direct write then verify path
    from company_brain.wiki.publish import write_wiki_page

    write_wiki_page(
        "admin/investor-newsletter/2026-06.md",
        "Investor Update 2026-06",
        "# Investor Update 2026-06\n\nContact us at founder@example.com\n\n_Status: draft_\n",
        mode="update",
        section="admin",
        sync=False,
        sources=["product/feature.md"],
        extra_frontmatter={"sync": "admin_only"},
    )
    result = agent.verify(
        {
            "status": "ok",
            "wiki_path": "admin/investor-newsletter/2026-06.md",
            "sources": ["product/feature.md"],
        }
    )
    assert result.status == "rework"
