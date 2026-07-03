"""Tests for CRM Notion database row sync."""

from unittest.mock import MagicMock, patch

from company_brain.config import CrmDatabaseColumns, CrmDatabaseSpec, NotionConfig
from company_brain.crm.notion_sync import (
    crm_database_key_for_rel_path,
    sync_crm_doc,
)
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


def _notion_with_crm(db_id: str = "db-crm") -> NotionConfig:
    cols = CrmDatabaseColumns()
    spec = CrmDatabaseSpec(database_id=db_id, columns=cols)
    return NotionConfig(
        crm_databases={
            "crm_contacts": spec,
            "inbound_press_podcast": spec,
        },
    )


def test_crm_database_key_for_contact_and_inbound():
    assert crm_database_key_for_rel_path("crm/contact/jane-doe-acme-com.md") == "crm_contacts"
    assert (
        crm_database_key_for_rel_path("crm/inbound/press-podcast/2026-07-02-intro.md")
        == "inbound_press_podcast"
    )
    assert crm_database_key_for_rel_path("crm/customer/_index.md") is None
    assert crm_database_key_for_rel_path("crm/inbound/unmatched/foo.md") is None


def test_sync_crm_contact_creates_row(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))

    rel = "crm/contact/jane-doe-acme-com.md"
    store = LocalWikiStore(root=wiki)
    store.write(
        rel,
        MarkdownDoc(
            frontmatter={
                "title": "Jane Doe",
                "segment": "connection",
                "canonical_email": "jane@acme.com",
                "main_connection_employee": "nicky",
                "status": "active",
                "section": "crm",
            },
            body="## Interactions\n",
        ),
    )

    config = MagicMock()
    config.notion = _notion_with_crm()

    mock_client = MagicMock()
    api_results = [
        MagicMock(json_data={"properties": {"Name": {"type": "title"}}}),
        MagicMock(json_data={"results": []}),
        MagicMock(json_data={"id": "page-new", "url": "https://notion.so/page-new"}),
    ]
    mock_client.api.side_effect = api_results

    with patch(
        "company_brain.crm.notion_sync.notion_db.notion_is_available",
        return_value=True,
    ):
        page_id = sync_crm_doc(rel, store=store, client=mock_client, config=config)

    assert page_id == "page-new"
    updated = store.read(rel)
    assert updated.frontmatter.get("notion_page_id") == "page-new"
    assert updated.frontmatter.get("synced_hash")


def test_sync_crm_inbound_updates_existing_row(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))

    rel = "crm/inbound/press-podcast/2026-07-02-intro.md"
    store = LocalWikiStore(root=wiki)
    store.write(
        rel,
        MarkdownDoc(
            frontmatter={
                "title": "Podcast invite",
                "inbound_type": "press-podcast",
                "contact_slug": "jane-doe-acme-com",
                "score": 8,
                "status": "open",
                "received_at": "2026-07-02T10:00:00Z",
                "notion_page_id": "page-existing",
                "section": "crm",
            },
            body="Preview text",
        ),
    )

    config = MagicMock()
    config.notion = _notion_with_crm()

    mock_client = MagicMock()
    mock_client.api.return_value = MagicMock(
        json_data={"id": "page-existing", "properties": {}},
    )

    with patch(
        "company_brain.crm.notion_sync.notion_db.notion_is_available",
        return_value=True,
    ):
        page_id = sync_crm_doc(rel, store=store, client=mock_client, config=config)

    assert page_id == "page-existing"
    updated = store.read(rel)
    assert updated.frontmatter.get("synced_hash")
    assert mock_client.api.called


def test_sync_skips_when_database_id_empty(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))

    rel = "crm/contact/jane-doe-acme-com.md"
    store = LocalWikiStore(root=wiki)
    store.write(
        rel,
        MarkdownDoc(frontmatter={"title": "Jane Doe", "section": "crm"}, body=""),
    )

    config = MagicMock()
    config.notion = NotionConfig(crm_databases={"crm_contacts": CrmDatabaseSpec()})

    with patch(
        "company_brain.crm.notion_sync.notion_db.notion_is_available",
        return_value=True,
    ):
        assert sync_crm_doc(rel, store=store, config=config) is None
