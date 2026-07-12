"""Tests for Notion teamspace defaults + bidirectional sync (Sessions 1–2)."""

from __future__ import annotations

from unittest.mock import MagicMock

from company_brain.agents.operations.notion.sync_pull import SyncPullAgent
from company_brain.config import AppConfig, NotionConfig, load_config
from company_brain.notion.sync import NotionSync
from company_brain.notion.sync_policy import (
    SyncAction,
    body_hash,
    decide_pull_push,
    should_skip_push_for_signature,
    try_compatible_merge,
)
from company_brain.notion.sync_routing import resolve_sync_parent, resolve_teamspace_parent
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


def _cfg(**teamspaces: str) -> AppConfig:
    return AppConfig(
        wiki=load_config().wiki,
        notion=NotionConfig(
            root_page_id="root-page",
            teamspaces={
                "admin": "admin-parent",
                "company": "company-parent",
                **teamspaces,
            },
            section_teamspace={
                "admin": "admin",
                "finance": "admin",
                "engineering": "company",
                "product": "company",
                "growth": "company",
            },
        ),
    )


def test_default_engineering_falls_back_to_company():
    cfg = _cfg()
    assert resolve_teamspace_parent("engineering", cfg) == "company-parent"
    assert resolve_sync_parent({"sync": "location:engineering"}, cfg) == "company-parent"
    assert cfg.notion.teamspace_for_section("engineering/github") == "company"


def test_optional_engineering_split_uses_own_parent():
    cfg = _cfg(engineering="eng-parent")
    assert resolve_teamspace_parent("engineering", cfg) == "eng-parent"
    assert resolve_sync_parent({"sync": "location:engineering"}, cfg) == "eng-parent"


def test_product_and_growth_fallback():
    cfg = _cfg()
    assert resolve_teamspace_parent("product", cfg) == "company-parent"
    assert resolve_teamspace_parent("growth", cfg) == "company-parent"


def test_decide_noop_when_equal():
    body = "# Title\n\nHello\n"
    d = decide_pull_push(md_body=body, notion_body=body, synced_hash=body_hash(body))
    assert d.action == SyncAction.NOOP


def test_decide_pull_when_notion_ahead():
    md = "# T\n\nAgent text\n"
    notion = "# T\n\nHuman edit\n"
    synced = body_hash(md)
    d = decide_pull_push(md_body=md, notion_body=notion, synced_hash=synced)
    assert d.action == SyncAction.PULL


def test_decide_push_when_md_ahead():
    base = "# T\n\nBase\n"
    md = "# T\n\nMD newer\n"
    notion = base
    d = decide_pull_push(md_body=md, notion_body=notion, synced_hash=body_hash(base))
    assert d.action == SyncAction.PUSH


def test_decide_merge_when_compatible():
    md = "# T\n\nHello\n"
    notion = "# T\n\nHello\n\nExtra line\n"
    synced = "sha256:not-either"
    d = decide_pull_push(md_body=md, notion_body=notion, synced_hash=synced)
    assert d.action == SyncAction.MERGE
    assert d.merged_body is not None
    assert "Extra line" in d.merged_body


def test_decide_conflict_when_incompatible():
    md = "# T\n\nAlpha\n"
    notion = "# T\n\nBeta\n"
    d = decide_pull_push(md_body=md, notion_body=notion, synced_hash="sha256:other")
    assert d.action == SyncAction.CONFLICT


def test_signature_gate_skips_when_same_sig_and_diverged():
    assert (
        should_skip_push_for_signature(
            agent_signature="sig-1",
            pushed_agent_signature="sig-1",
            md_body="agent body",
            notion_body="human body",
        )
        is True
    )


def test_signature_gate_allows_when_signature_changed():
    assert (
        should_skip_push_for_signature(
            agent_signature="sig-2",
            pushed_agent_signature="sig-1",
            md_body="new agent",
            notion_body="human body",
        )
        is False
    )


def test_try_compatible_merge_superset():
    assert try_compatible_merge("a", "a\nb") == "a\nb"


def test_notion_sync_signature_gate_restores_human(tmp_path):
    store = LocalWikiStore(root=tmp_path)
    store.write(
        "engineering/open-pr.md",
        MarkdownDoc(
            frontmatter={
                "title": "Open PRs",
                "notion_page_id": "page-1",
                "agent_signature": "sig-a",
                "pushed_agent_signature": "sig-a",
                "synced_hash": body_hash("# Open PRs\n\nPR list\n"),
            },
            body="# Open PRs\n\nPR list regenerated\n",
        ),
    )
    client = MagicMock()
    client.get_page_markdown.return_value = (
        "# Open PRs\n\nHuman trimmed list\n",
        "2026-07-12T00:00:00Z",
    )
    cfg = _cfg()
    syncer = NotionSync(store=store, client=client, config=cfg, registry=MagicMock())
    syncer.registry.load = MagicMock()
    page_id = syncer.sync_doc("engineering/open-pr.md")
    assert page_id == "page-1"
    client.update_page.assert_not_called()
    doc = store.read("engineering/open-pr.md")
    assert "Human trimmed list" in doc.body
    assert doc.frontmatter.get("human_override_note")


def test_notion_sync_new_signature_overwrites(tmp_path):
    store = LocalWikiStore(root=tmp_path)
    store.write(
        "engineering/open-pr.md",
        MarkdownDoc(
            frontmatter={
                "title": "Open PRs",
                "notion_page_id": "page-1",
                "agent_signature": "sig-b",
                "pushed_agent_signature": "sig-a",
                "human_override_note": "old human note",
                "synced_hash": body_hash("old"),
            },
            body="# Open PRs\n\nFresh factual\n",
        ),
    )
    client = MagicMock()
    client.get_page_markdown.return_value = ("# Open PRs\n\nHuman\n", None)
    cfg = _cfg()
    syncer = NotionSync(store=store, client=client, config=cfg, registry=MagicMock())
    syncer.registry.register = MagicMock()
    syncer.registry.save = MagicMock()
    page_id = syncer.sync_doc("engineering/open-pr.md")
    assert page_id == "page-1"
    client.update_page.assert_called_once()
    doc = store.read("engineering/open-pr.md")
    assert doc.frontmatter.get("pushed_agent_signature") == "sig-b"
    assert doc.frontmatter.get("prior_human_override") == "old human note"
    assert "human_override_note" not in doc.frontmatter


def test_sync_pull_pulls_notion_ahead(tmp_path):
    store = LocalWikiStore(root=tmp_path)
    md = "# Page\n\nMD synced\n"
    store.write(
        "company/note.md",
        MarkdownDoc(
            frontmatter={
                "title": "Note",
                "notion_page_id": "page-9",
                "synced_hash": body_hash(md),
                "agent_signature": "s1",
                "pushed_agent_signature": "s1",
            },
            body=md,
        ),
    )
    client = MagicMock()
    client.is_installed.return_value = True
    client.check_auth.return_value = True
    client.get_page_markdown.return_value = ("# Page\n\nHuman wrote more\n", None)

    cfg = _cfg()
    agent = SyncPullAgent(cfg, store=store, client=client)
    result = agent.run()
    assert result["pulled"] == 1
    doc = store.read("company/note.md")
    assert "Human wrote more" in doc.body
    assert doc.frontmatter.get("human_override_note")


def test_sync_pull_marks_conflict(tmp_path):
    store = LocalWikiStore(root=tmp_path)
    store.write(
        "company/note.md",
        MarkdownDoc(
            frontmatter={
                "title": "Note",
                "notion_page_id": "page-9",
                "synced_hash": body_hash("baseline different"),
            },
            body="# Page\n\nMD side\n",
        ),
    )
    client = MagicMock()
    client.is_installed.return_value = True
    client.check_auth.return_value = True
    client.get_page_markdown.return_value = ("# Page\n\nNotion side\n", None)

    agent = SyncPullAgent(_cfg(), store=store, client=client)
    result = agent.run()
    assert result["conflicts"] == 1
    doc = store.read("company/note.md")
    assert doc.frontmatter.get("sync_conflict")
    assert "MD side" in doc.body
