"""CRM slug helpers — stable kebab-case ids from email or domain."""

from __future__ import annotations

import re

_SLUG_SAFE = re.compile(r"[^a-z0-9]+")


def slug_from_email(email: str) -> str:
    """Build contact slug from an email address (e.g. jane@acme.com → jane-acme-com)."""
    local, _, domain = email.lower().partition("@")
    if not domain:
        return _slugify(local or email)
    local_part = _slugify(local) or "contact"
    domain_part = domain.replace(".", "-")
    return f"{local_part}-{domain_part}"


def slug_from_domain(domain: str) -> str:
    """Build slug for domain-only index entries (e.g. acme.com → acme-com)."""
    return domain.lower().strip().replace(".", "-")


def _slugify(value: str) -> str:
    return _SLUG_SAFE.sub("-", value.lower()).strip("-")
