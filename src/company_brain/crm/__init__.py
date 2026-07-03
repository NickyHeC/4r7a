"""Company CRM — entity-per-person contacts, inbound items, and registry."""

from company_brain.crm.registry import CrmRegistry, lookup_contact, rebuild_registry

__all__ = ["CrmRegistry", "lookup_contact", "rebuild_registry"]
