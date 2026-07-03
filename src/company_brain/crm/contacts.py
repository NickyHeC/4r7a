"""CRM contact page read/write helpers."""

from __future__ import annotations

import re

from company_brain.config import resolve_wiki_dir
from company_brain.crm.config import contact_rel_path, default_connection_employee
from company_brain.crm.registry import rebuild_registry
from company_brain.crm.schema import DEFAULT_CONTACT_BODY, ContactEntity
from company_brain.crm.slug import slug_from_email
from company_brain.wiki.publish import APPEND, UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore


def read_contact(slug: str, *, wiki_root=None) -> ContactEntity | None:
    store = LocalWikiStore(root=wiki_root or resolve_wiki_dir())
    rel = contact_rel_path(slug)
    if not store.exists(rel):
        return None
    doc = store.read(rel)
    return ContactEntity.from_doc(slug, doc.frontmatter, doc.body)


def write_contact(entity: ContactEntity, *, wiki_root=None, rebuild: bool = True) -> str:
    entity.validate()
    rel = contact_rel_path(entity.slug)
    body = entity.body.strip() or DEFAULT_CONTACT_BODY.strip()
    write_wiki_page(
        rel,
        entity.title,
        body,
        mode=UPDATE,
        section="crm",
        extra_frontmatter=entity.to_frontmatter(),
        sync=False,
    )
    if rebuild:
        rebuild_registry(wiki_root=wiki_root)
    return rel


def append_contact_interaction(slug: str, section: str, *, wiki_root=None) -> None:
    """Append an inbound section under ## Interactions on a contact page."""
    rel = contact_rel_path(slug)
    entity = read_contact(slug, wiki_root=wiki_root)
    if entity is None:
        raise FileNotFoundError(rel)
    write_wiki_page(
        rel,
        entity.title,
        section,
        mode=APPEND,
        section="crm",
        sync=False,
    )


def ensure_contact_for_email(
    email: str,
    *,
    title: str,
    segment: str = "connection",
    main_connection_employee: str = "",
    wiki_root=None,
    rebuild: bool = True,
) -> ContactEntity:
    slug = slug_from_email(email)
    existing = read_contact(slug, wiki_root=wiki_root)
    if existing:
        return existing
    entity = ContactEntity(
        slug=slug,
        title=title,
        segment=segment,
        canonical_email=email.lower(),
        main_connection_employee=main_connection_employee,
    )
    write_contact(entity, wiki_root=wiki_root, rebuild=rebuild)
    return entity


_EMAIL_FROM = re.compile(r"<([^>]+)>|([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})")


def email_from_from_header(from_hdr: str) -> str:
    for match in _EMAIL_FROM.finditer(from_hdr):
        email = (match.group(1) or match.group(2) or "").strip().lower()
        if "@" in email:
            return email
    return ""


def display_name_from_from_header(from_hdr: str, *, fallback: str = "Contact") -> str:
    if "<" in from_hdr:
        name = from_hdr.split("<", 1)[0].strip().strip('"')
        if name:
            return name
    email = email_from_from_header(from_hdr)
    if email:
        return email.split("@", 1)[0].replace(".", " ").title()
    return fallback


def record_interaction_on_contact(
    from_hdr: str,
    section: str,
    *,
    segment: str,
    title: str | None = None,
    main_connection_employee: str = "",
    wiki_root=None,
) -> str | None:
    """Ensure a contact entity exists and append an interaction section."""
    email = email_from_from_header(from_hdr)
    if not email:
        return None
    employee = main_connection_employee or default_connection_employee()
    if segment == "connection" and not employee:
        raise ValueError(
            "connection segment needs main_connection_employee or crm.default_connection_employee"
        )
    entity = ensure_contact_for_email(
        email,
        title=title or display_name_from_from_header(from_hdr),
        segment=segment,
        main_connection_employee=employee if segment == "connection" else "",
        wiki_root=wiki_root,
        rebuild=False,
    )
    append_contact_interaction(entity.slug, section, wiki_root=wiki_root)
    rebuild_registry(wiki_root=wiki_root)
    return entity.slug
