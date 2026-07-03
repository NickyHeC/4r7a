"""CRM registry — derived email/domain → slug + segment index."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from company_brain.agents.operations.shared.contact_lists import load_contacts
from company_brain.config import resolve_wiki_dir
from company_brain.crm.config import (
    contact_dir,
    customer_index_path,
    investor_index_path,
    registry_path,
)
from company_brain.crm.schema import ContactEntity
from company_brain.crm.slug import slug_from_domain, slug_from_email
from company_brain.wiki.store import LocalWikiStore

logger = logging.getLogger(__name__)

REGISTRY_VERSION = 1


@dataclass
class RegistryEntry:
    slug: str
    segment: str
    source: str = "contact"

    def to_dict(self) -> dict[str, str]:
        return {"slug": self.slug, "segment": self.segment, "source": self.source}


@dataclass
class CrmRegistry:
    version: int = REGISTRY_VERSION
    by_email: dict[str, RegistryEntry] = field(default_factory=dict)
    by_domain: dict[str, RegistryEntry] = field(default_factory=dict)
    updated_at: str = ""

    def lookup_email(self, email: str) -> RegistryEntry | None:
        return self.by_email.get(email.lower())

    def lookup_domain(self, domain: str) -> RegistryEntry | None:
        return self.by_domain.get(domain.lower())

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "by_email": {k: v.to_dict() for k, v in sorted(self.by_email.items())},
            "by_domain": {k: v.to_dict() for k, v in sorted(self.by_domain.items())},
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CrmRegistry":
        by_email = {k: RegistryEntry(**v) for k, v in (data.get("by_email") or {}).items()}
        by_domain = {k: RegistryEntry(**v) for k, v in (data.get("by_domain") or {}).items()}
        return cls(
            version=int(data.get("version") or REGISTRY_VERSION),
            by_email=by_email,
            by_domain=by_domain,
            updated_at=str(data.get("updated_at") or ""),
        )


def load_registry(*, wiki_root=None) -> CrmRegistry:
    store = LocalWikiStore(root=wiki_root or resolve_wiki_dir())
    rel = registry_path()
    if not store.exists(rel):
        return CrmRegistry()
    raw = store.abspath(rel).read_text(encoding="utf-8")
    return CrmRegistry.from_dict(json.loads(raw))


def save_registry(registry: CrmRegistry, *, wiki_root=None) -> None:
    store = LocalWikiStore(root=wiki_root or resolve_wiki_dir())
    rel = registry_path()
    registry.updated_at = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(registry.to_dict(), indent=2, sort_keys=True) + "\n"
    path = store.abspath(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def rebuild_registry(*, wiki_root=None) -> CrmRegistry:
    """Rebuild ``crm/_registry.json`` from contact pages and segment indexes."""
    store = LocalWikiStore(root=wiki_root or resolve_wiki_dir())
    registry = CrmRegistry()
    conflicts: list[str] = []

    _ingest_contacts(store, registry, conflicts)
    _ingest_index(store, customer_index_path(), "customer", registry, conflicts)
    _ingest_index(store, investor_index_path(), "investor", registry, conflicts)

    for msg in conflicts:
        logger.warning("crm registry conflict: %s", msg)

    save_registry(registry, wiki_root=wiki_root)
    return registry


def lookup_contact(from_hdr: str, *, wiki_root=None) -> RegistryEntry | None:
    """Resolve a From header to a registry entry (email first, then domain)."""
    registry = load_registry(wiki_root=wiki_root)
    lower = from_hdr.lower()
    for email, entry in registry.by_email.items():
        if email in lower:
            return entry
    for domain, entry in registry.by_domain.items():
        if domain in lower:
            return entry
    return None


def _ingest_contacts(store: LocalWikiStore, registry: CrmRegistry, conflicts: list[str]) -> None:
    prefix = contact_dir().rstrip("/") + "/"
    for rel in store.list(prefix):
        if not rel.endswith(".md"):
            continue
        slug = PurePosixPath(rel).stem
        doc = store.read(rel)
        try:
            entity = ContactEntity.from_doc(slug, doc.frontmatter, doc.body)
        except Exception as exc:
            logger.warning("skip contact %s: %s", rel, exc)
            continue
        if entity.status == "archived":
            continue
        entry = RegistryEntry(slug=slug, segment=entity.segment, source="contact")
        _register_email(registry, entity.canonical_email, entry, conflicts)
        for alias in entity.aliases:
            _register_email(registry, alias, entry, conflicts)
        if entity.canonical_domain:
            _register_domain(registry, entity.canonical_domain, entry, conflicts)


def _ingest_index(
    store: LocalWikiStore,
    rel_path: str,
    segment: str,
    registry: CrmRegistry,
    conflicts: list[str],
) -> None:
    emails, domains = load_contacts(rel_path) if store.exists(rel_path) else (set(), set())
    for email in emails:
        entry = RegistryEntry(slug=slug_from_email(email), segment=segment, source="index")
        _register_email(registry, email, entry, conflicts)
    for domain in domains:
        entry = RegistryEntry(slug=slug_from_domain(domain), segment=segment, source="index")
        _register_domain(registry, domain, entry, conflicts)


def _register_email(
    registry: CrmRegistry,
    email: str,
    entry: RegistryEntry,
    conflicts: list[str],
) -> None:
    if not email:
        return
    key = email.lower()
    existing = registry.by_email.get(key)
    if existing and (existing.slug != entry.slug or existing.segment != entry.segment):
        if existing.source == "contact" and entry.source == "index":
            return
        if existing.source == "index" and entry.source == "contact":
            registry.by_email[key] = entry
            return
        conflicts.append(
            f"email {key}: {existing.slug}/{existing.segment} vs {entry.slug}/{entry.segment}"
        )
        return
    registry.by_email[key] = entry


def _register_domain(
    registry: CrmRegistry,
    domain: str,
    entry: RegistryEntry,
    conflicts: list[str],
) -> None:
    if not domain:
        return
    key = domain.lower()
    existing = registry.by_domain.get(key)
    if existing and (existing.slug != entry.slug or existing.segment != entry.segment):
        if existing.source == "contact" and entry.source == "index":
            return
        if existing.source == "index" and entry.source == "contact":
            registry.by_domain[key] = entry
            return
        conflicts.append(
            f"domain {key}: {existing.slug}/{existing.segment} vs {entry.slug}/{entry.segment}"
        )
        return
    registry.by_domain[key] = entry
