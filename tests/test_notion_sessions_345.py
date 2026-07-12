"""Tests for Notion Sessions 3–5: @wiki, conflicts, page_system."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from company_brain.agents.operations.notion.conflict_apply import ConflictApplyAgent
from company_brain.agents.operations.notion.conflict_resolution import ConflictResolutionAgent
from company_brain.agents.operations.notion.conflict_store import evidence_winner
from company_brain.agents.operations.notion.page_system import PageSystemAgent
from company_brain.agents.operations.notion.wiki_directive import WikiDirectiveAgent
from company_brain.config import AppConfig, NotionConfig, load_config
from company_brain.notion.wiki_directive import extract_directives, parse_instruction
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


def _cfg() -> AppConfig:
    return AppConfig(
        wiki=load_config().wiki,
        notion=NotionConfig(
            root_page_id="root-page",
            teamspaces={"admin": "admin-parent", "company": "company-parent"},
            section_teamspace={
                "admin": "admin",
                "engineering": "company",
                "operations": "company",
                "product": "company",
            },
        ),
    )


def test_parse_fill_and_move():
    d = parse_instruction("move to engineering/github/open-pr.md and fill from standup")
    assert d.move_to == "engineering/github/open-pr.md"
    assert d.want_fill is True


def test_parse_external_only():
    d = parse_instruction("mark external")
    assert d.mark_external is True
    assert d.want_fill is False


def test_parse_move_only():
    d = parse_instruction("move to product/roadmap.md")
    assert d.move_to == "product/roadmap.md"
    assert d.want_fill is False


def test_extract_strips_directive_lines():
    body = "# Title\n\nHello\n\n@wiki fill with partner notes\n\nMore\n"
    directives, cleaned = extract_directives(body)
    assert len(directives) == 1
    assert directives[0].want_fill is True
    assert "@wiki" not in cleaned
    assert "Hello" in cleaned and "More" in cleaned


def test_wiki_directive_fill_scoped(tmp_path):
    store = LocalWikiStore(root=tmp_path)
    store.write(
        "engineering/context.md",
        MarkdownDoc(
            frontmatter={"title": "Context", "section": "engineering"},
            body="# Context\n\nAcme partnership details and timeline.\n",
        ),
    )
    store.write(
        "engineering/draft.md",
        MarkdownDoc(
            frontmatter={"title": "Draft", "section": "engineering", "sync": "company"},
            body="# Draft\n\nThin page.\n\n@wiki fill with Acme partnership\n",
        ),
    )
    agent = WikiDirectiveAgent(_cfg(), store=store, sync=False)
    result = agent.run()
    assert result["filled"] == 1
    doc = store.read("engineering/draft.md")
    assert "@wiki" not in doc.body
    assert "Wiki fill" in doc.body
    assert "Acme" in doc.body or "partnership" in doc.body.lower()


def test_wiki_directive_skips_external_without_fill(tmp_path):
    store = LocalWikiStore(root=tmp_path)
    store.write(
        "company/public.md",
        MarkdownDoc(
            frontmatter={
                "title": "Public",
                "section": "company",
                "external": True,
            },
            body="# Public\n\n@wiki add more marketing copy\n",
        ),
    )
    agent = WikiDirectiveAgent(_cfg(), store=store, sync=False)
    result = agent.run()
    assert result["filled"] == 0
    assert result["skipped"] >= 1
    assert "@wiki" not in store.read("company/public.md").body


def test_wiki_directive_move_leaves_stub(tmp_path):
    store = LocalWikiStore(root=tmp_path)
    store.write(
        "company/wrong.md",
        MarkdownDoc(
            frontmatter={"title": "Wrong Spot", "section": "company"},
            body="# Wrong Spot\n\nContent here.\n\n@wiki move to engineering/right.md\n",
        ),
    )
    agent = WikiDirectiveAgent(_cfg(), store=store, sync=False)
    result = agent.run()
    assert result["moved"] == 1
    assert store.exists("engineering/right.md")
    stub = store.read("company/wrong.md")
    assert stub.frontmatter.get("stub") is True
    assert "engineering/right" in stub.body


def test_evidence_winner_clear_margin():
    md = "alpha beta gamma delta epsilon"
    notion = "zeta eta theta"
    snippets = [
        {"title": "S1", "snippet": "alpha beta gamma delta meeting notes"},
        {"title": "S2", "snippet": "alpha gamma epsilon slack thread"},
    ]
    assert evidence_winner(md, notion, snippets, margin=2, min_hits=3) == "md"


def test_evidence_winner_unclear():
    assert (
        evidence_winner("a b c", "x y z", [{"title": "t", "snippet": "hello"}], min_hits=4) is None
    )


def test_conflict_resolution_auto(tmp_path):
    store = LocalWikiStore(root=tmp_path)
    store.write(
        "operations/evidence.md",
        MarkdownDoc(
            frontmatter={"title": "Evidence", "section": "operations"},
            body="# Evidence\n\nUniqueZebraTopic appears in meetings and slack.\n",
        ),
    )
    store.write(
        "operations/conflicted.md",
        MarkdownDoc(
            frontmatter={
                "title": "Conflicted",
                "section": "operations",
                "sync_conflict": "both_changed",
                "conflict_notion_body": "# Conflicted\n\nTotallyOtherSide\n",
            },
            body="# Conflicted\n\nUniqueZebraTopic UniqueZebraTopic UniqueZebraTopic\n",
        ),
    )
    # Seed another evidence page
    store.write(
        "operations/notes.md",
        MarkdownDoc(
            frontmatter={"title": "Notes", "section": "operations"},
            body="# Notes\n\nUniqueZebraTopic clarification from email.\n",
        ),
    )
    agent = ConflictResolutionAgent(_cfg(), store=store, client=MagicMock(), sync=False)
    # Lower bar for test via patch
    with patch(
        "company_brain.agents.operations.notion.conflict_resolution.store_mod.evidence_winner",
        return_value="md",
    ):
        result = agent.run()
    assert result["auto_resolved"] == 1
    doc = store.read("operations/conflicted.md")
    assert "sync_conflict" not in doc.frontmatter
    assert store.exists("operations/notion/conflict-resolution.md")


def test_conflict_resolution_escalates(tmp_path):
    store = LocalWikiStore(root=tmp_path)
    store.write(
        "operations/conflicted.md",
        MarkdownDoc(
            frontmatter={
                "title": "Conflicted",
                "section": "operations",
                "sync_conflict": "both_changed",
                "conflict_notion_body": "# N\n\nNotion side\n",
            },
            body="# Conflicted\n\nMD side\n",
        ),
    )
    client = MagicMock()
    client.is_installed.return_value = False
    agent = ConflictResolutionAgent(_cfg(), store=store, client=client, sync=False)
    with patch(
        "company_brain.agents.operations.notion.conflict_resolution.store_mod.evidence_winner",
        return_value=None,
    ):
        result = agent.run()
    assert result["escalated"] == 1
    doc = store.read("operations/conflicted.md")
    assert doc.frontmatter.get("conflict_enqueued") is True
    assert store.exists("operations/notion/conflict-resolution.md")


def test_conflict_apply_admin_md(tmp_path):
    store = LocalWikiStore(root=tmp_path)
    store.write(
        "operations/conflicted.md",
        MarkdownDoc(
            frontmatter={
                "title": "Conflicted",
                "sync_conflict": "both_changed",
                "conflict_notion_body": "notion",
                "conflict_enqueued": True,
            },
            body="# Conflicted\n\nMD wins\n",
        ),
    )
    row = {
        "id": "row-1",
        "properties": {
            "Title": {"type": "title", "title": [{"plain_text": "Conflict"}]},
            "Status": {"type": "status", "status": {"name": "resolved_md"}},
            "Path": {
                "type": "rich_text",
                "rich_text": [{"plain_text": "operations/conflicted.md"}],
            },
            "Reason": {"type": "rich_text", "rich_text": [{"plain_text": "both"}]},
            "Winner": {"type": "rich_text", "rich_text": [{"plain_text": ""}]},
        },
    }
    agent = ConflictApplyAgent(_cfg(), store=store, client=MagicMock(), sync=False)
    with patch(
        "company_brain.agents.operations.notion.conflict_apply.store_mod.database_id",
        return_value="",
    ):
        result = agent.run(rows=[row])
    assert result["applied"] == 1
    assert "sync_conflict" not in store.read("operations/conflicted.md").frontmatter


def test_page_system_expires_stub(tmp_path):
    store = LocalWikiStore(root=tmp_path)
    past = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    store.write(
        "company/old-stub.md",
        MarkdownDoc(
            frontmatter={
                "title": "Stub",
                "stub": True,
                "stub_target": "engineering/new.md",
                "stub_expires_at": past,
            },
            body="# Stub\n",
        ),
    )
    agent = PageSystemAgent(_cfg(), store=store, sync=False)
    result = agent.run()
    assert result["stubs_removed"] == 1
    assert not store.exists("company/old-stub.md")


def test_page_system_relocate_flag(tmp_path):
    store = LocalWikiStore(root=tmp_path)
    store.write(
        "company/misplaced.md",
        MarkdownDoc(
            frontmatter={
                "title": "Misplaced",
                "section": "company",
                "page_relocate_to": "product/feature.md",
            },
            body="# Misplaced\n\nReal content.\n",
        ),
    )
    agent = PageSystemAgent(_cfg(), store=store, client=MagicMock(), sync=False)
    result = agent.run()
    assert result["relocated"] == 1
    assert store.exists("product/feature.md")
    assert store.read("company/misplaced.md").frontmatter.get("stub") is True
