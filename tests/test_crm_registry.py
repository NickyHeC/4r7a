"""Tests for CRM registry rebuild and contact helpers."""

from __future__ import annotations

import json

from company_brain.crm.contacts import ensure_contact_for_email, write_contact
from company_brain.crm.registry import load_registry, lookup_contact, rebuild_registry
from company_brain.crm.schema import ContactEntity
from company_brain.crm.seeds import ensure_crm_seeds
from company_brain.crm.slug import slug_from_email
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


def test_slug_from_email():
    assert slug_from_email("Jane.Doe@Acme.COM") == "jane-doe-acme-com"


def test_ensure_crm_seeds_and_rebuild_empty(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))

    created = ensure_crm_seeds()
    assert created >= 4

    store = LocalWikiStore(root=wiki)
    assert store.exists("crm/customer/_index.md")
    assert store.exists("crm/investor/_index.md")
    assert store.exists("crm/lead/_index.md")
    assert store.exists("crm/promotion-log.md")

    registry = rebuild_registry()
    assert registry.by_email == {}
    assert store.exists("crm/_registry.json")


def test_registry_from_contact_and_indexes(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    ensure_crm_seeds()

    store = LocalWikiStore(root=wiki)
    store.write(
        "crm/customer/_index.md",
        MarkdownDoc(body="# Customers\n\n- buyer@client.com\n- client.com\n"),
    )
    entity = ContactEntity(
        slug="pat-sequoia-com",
        title="Pat Lee",
        segment="connection",
        canonical_email="pat@sequoia.com",
        main_connection_employee="nicky",
    )
    write_contact(entity, rebuild=False)
    rebuild_registry()

    registry = load_registry()
    assert registry.lookup_email("buyer@client.com").segment == "customer"
    assert registry.lookup_email("pat@sequoia.com").segment == "connection"
    assert registry.lookup_domain("client.com").segment == "customer"
    assert lookup_contact("Pat <pat@sequoia.com>").segment == "connection"


def test_contact_page_overrides_index_segment(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    ensure_crm_seeds()

    store = LocalWikiStore(root=wiki)
    store.write(
        "crm/investor/_index.md",
        MarkdownDoc(body="# Investors\n\n- dual@firm.com\n"),
    )
    entity = ContactEntity(
        slug="dual-firm-com",
        title="Dual Role",
        segment="connection",
        canonical_email="dual@firm.com",
        main_connection_employee="nicky",
    )
    write_contact(entity, rebuild=False)
    registry = rebuild_registry()
    assert registry.lookup_email("dual@firm.com").segment == "connection"
    assert registry.lookup_email("dual@firm.com").source == "contact"


def test_ensure_contact_for_email_idempotent(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    ensure_crm_seeds()

    first = ensure_contact_for_email(
        "new@startup.io",
        title="New Founder",
        segment="connection",
        main_connection_employee="nicky",
    )
    second = ensure_contact_for_email(
        "new@startup.io",
        title="Other",
        segment="connection",
        main_connection_employee="nicky",
    )
    assert first.slug == second.slug == "new-startup-io"
    registry = load_registry()
    assert registry.lookup_email("new@startup.io").slug == "new-startup-io"


def test_registry_json_roundtrip(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    ensure_crm_seeds()
    rebuild_registry()

    raw = json.loads((wiki / "crm/_registry.json").read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert "updated_at" in raw


def test_lead_segment_contact_and_index(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    ensure_crm_seeds()

    store = LocalWikiStore(root=wiki)
    store.write(
        "crm/lead/_index.md",
        MarkdownDoc(body="# Leads\n\n- prospect@startup.io\n"),
    )
    entity = ContactEntity(
        slug="alex-buyer-com",
        title="Alex Buyer",
        segment="lead",
        canonical_email="alex@buyer.com",
        priority=7,
        sources=["event:demo-day"],
    )
    write_contact(entity, rebuild=False)
    registry = rebuild_registry()
    assert registry.lookup_email("prospect@startup.io").segment == "lead"
    assert registry.lookup_email("alex@buyer.com").segment == "lead"
    loaded = ensure_contact_for_email(
        "alex@buyer.com",
        title="Alex Buyer",
        segment="lead",
    )
    assert loaded.priority == 7
    assert loaded.segment == "lead"
