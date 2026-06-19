"""Parse confirmed contact lists from wiki CRM pages ($0)."""

from __future__ import annotations

import re

from company_brain.config import resolve_wiki_dir
from company_brain.wiki.store import LocalWikiStore

_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_DOMAIN = re.compile(r"(?:^|\s)([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(?:\s|$)")


def load_contacts(rel_path: str) -> tuple[set[str], set[str]]:
    """Return (emails, domains) extracted from a wiki markdown page."""
    store = LocalWikiStore(root=resolve_wiki_dir())
    if not store.exists(rel_path):
        return set(), set()
    body = store.read(rel_path).body
    emails = {m.lower() for m in _EMAIL.findall(body)}
    domains: set[str] = set()
    for line in body.splitlines():
        line = line.strip().lstrip("-*").strip()
        if "@" in line:
            continue
        for match in _DOMAIN.findall(line):
            if match.count(".") >= 1 and not match.startswith("http"):
                domains.add(match.lower())
    return emails, domains


def matches_contact(from_hdr: str, emails: set[str], domains: set[str]) -> bool:
    lower = from_hdr.lower()
    for email in emails:
        if email in lower:
            return True
    for domain in domains:
        if domain in lower:
            return True
    return False
